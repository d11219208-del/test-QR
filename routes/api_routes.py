from flask import Blueprint, jsonify, request
from database import get_db_connection
from datetime import datetime
import re
import json  # 引入 json 模組來解析餐點欄位
import sys   # 用於直接印出錯誤到終端機

api_bp = Blueprint('api', __name__)

def _extract_chinese_from_list(items_list):
    """
    💡 核心輔助函式：從解析成功的 JSON 物件/列表中，精準抽取出中文名稱與選項
    """
    # 如果最外層是 dict（Object），試著找出裡面的陣列
    if isinstance(items_list, dict):
        if "items" in items_list: 
            items_list = items_list["items"]
        elif "data" in items_list: 
            items_list = items_list["data"]
        else: 
            items_list = [items_list]
        
    if not isinstance(items_list, list):
        return str(items_list)
        
    result_lines = []
    for index, item in enumerate(items_list):
        # 優先抓取中文品名 (name_zh)
        name_zh = item.get("name_zh", "")
        if not name_zh:
            name_zh = item.get("name", "未知商品")
            
        qty = item.get("qty", 1)
        item_line = f"{index + 1}. {name_zh} x {qty}"
        
        # 抓取客製化中文選項 (options_zh)
        options_zh = item.get("options_zh", [])
        if options_zh and isinstance(options_zh, list) and len(options_zh) > 0:
            item_line += f" ({', '.join(options_zh)})"
            
        result_lines.append(item_line)
    
    final_output = "\n".join(result_lines)
    print(f"[Debug] JSON 中文提取成功，最終輸出:\n{final_output}", file=sys.stderr)
    return final_output


def parse_items_to_chinese_only(items_raw_data):
    """
    💡 核心過濾器：將包含多國語言的 JSON 字串或已被污染的外文字串，淨化為純中文文字
    """
    print(f"=== [Debug] 收到 items 資料 ===", file=sys.stderr)
    print(f"原始型態: {type(items_raw_data)}", file=sys.stderr)
    print(f"原始內容: {repr(items_raw_data)}", file=sys.stderr)

    if not items_raw_data:
        return "無餐點資料"
    
    # 如果資料庫撈出來本身就是 list 或 dict 類型的物件，直接處理
    if isinstance(items_raw_data, (list, dict)):
        print(f"[Debug] 資料本身就是 Python 物件，直接進入解析", file=sys.stderr)
        return _extract_chinese_from_list(items_raw_data)

    # 強制轉為字串並去除前後空白
    cleaned_str = str(items_raw_data).strip()
    
    # ─── 【第一道防線】精準 JSON 解析 ───
    if cleaned_str.startswith('[') or cleaned_str.startswith('{'):
        try:
            items_list = json.loads(cleaned_str)
            print(f"[Debug] json.loads 解析成功！", file=sys.stderr)
            return _extract_chinese_from_list(items_list)
        except Exception as e:
            print(f"[Debug] json.loads 失敗，錯誤原因: {str(e)}", file=sys.stderr)
            pass

    # ─── 【第二道防線】非 JSON 的純外文字串強力濾鏡 ───
    print(f"[Debug] 判定非標準 JSON，進入文字過濾防線", file=sys.stderr)
    text = cleaned_str
    
    # 移除英日韓文
    text = re.sub(r'[\u3040-\u309F\u30A0-\u30FF]', '', text)
    text = re.sub(r'[\uAC00-\uD7A3\u1100-\u11FF]', '', text)
    text = re.sub(r'(?<!\d)[a-zA-Z](?!\d)', '', text)
    
    # 整理符號
    text = text.replace("()", "").replace("(,)", "")
    text = re.sub(r',\s*,', ',', text)
    text = re.sub(r'\+\s*\+', '+', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.replace(" + ", "\n").replace("+", "\n")
    
    print(f"[Debug] 文字過濾完成，輸出結果: {text}", file=sys.stderr)
    return text.strip()


# ==========================================
# 1. 獲取所有「待處理 (Pending)」的訂單
# ==========================================
@api_bp.route('/orders/pending', methods=['GET'])
def get_pending_orders():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, table_number, items, total_price, status, created_at, order_type 
            FROM orders 
            WHERE status = 'Pending'
            ORDER BY created_at ASC
        """)
        rows = cur.fetchall()
        
        orders = []
        for row in rows:
            orders.append({
                "id": row[0],
                "table_number": row[1],
                "items": parse_items_to_chinese_only(row[2]),
                "total_price": row[3],
                "status": row[4],
                "created_at": row[5].strftime('%Y-%m-%d %H:%M:%S') if row[5] else None,
                "order_type": row[6]
            })
        return jsonify({"success": True, "data": orders}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()


# ==========================================
# 2. 變更訂單狀態
# ==========================================
@api_bp.route('/orders/<int:order_id>/status', methods=['PUT'])
def update_order_status(order_id):
    data = request.get_json()
    new_status = data.get('status') 
    
    if not new_status:
        return jsonify({"success": False, "message": "缺少 status 欄位"}), 400
        
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status = %s WHERE id = %s", (new_status, order_id))
        conn.commit()
        return jsonify({"success": True, "message": f"訂單 {order_id} 狀態已更新為 {new_status}"}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()


# ==========================================
# 3. 區間營業報告
# ==========================================
@api_bp.route('/reports/revenue', methods=['GET'])
def get_revenue_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date or not end_date:
        return jsonify({"success": False, "message": "請提供 start_date 與 end_date"}), 400
        
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(SUM(total_price), 0), COUNT(id) 
            FROM orders 
            WHERE status = 'Completed' 
              AND created_at >= %s AND created_at <= %s
        """, (f"{start_date} 00:00:00", f"{end_date} 23:59:59"))
        row = cur.fetchone()
        return jsonify({
            "success": True, 
            "data": {
                "total_revenue": row[0],
                "order_count": row[1]
            }
        }), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()


# ==========================================
# 4. 銷售排行
# ==========================================
@api_bp.route('/reports/ranking', methods=['GET'])
def get_sales_ranking():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT items FROM orders 
            WHERE status = 'Completed' 
            ORDER BY created_at DESC LIMIT 50
        """)
        rows = cur.fetchall()
        items_list = [parse_items_to_chinese_only(row[0]) for row in rows]
        return jsonify({"success": True, "data": items_list}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()


# ==========================================
# 5. 歷史訂單查詢
# ==========================================
@api_bp.route('/orders/history', methods=['GET'])
def get_order_history():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, table_number, items, total_price, status, created_at, order_type 
            FROM orders 
            WHERE status != 'Pending'
            ORDER BY created_at DESC 
            LIMIT 100
        """)
        rows = cur.fetchall()
        
        orders = []
        for row in rows:
            orders.append({
                "id": row[0],
                "table_number": row[1],
                "items": parse_items_to_chinese_only(row[2]),
                "total_price": row[3],
                "status": row[4],
                "created_at": row[5].strftime('%Y-%m-%d %H:%M:%S') if row[5] else None,
                "order_type": row[6]
            })
        return jsonify({"success": True, "data": orders}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()
