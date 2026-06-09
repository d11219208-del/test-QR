from flask import Blueprint, jsonify, request
from database import get_db_connection
from datetime import datetime
import re
import json  # 💡 引入 json 模組來解析餐點欄位

api_bp = Blueprint('api', __name__)

def parse_items_to_chinese_only(items_raw_data):
    """
    💡 終極後端淨化器：不管是 JSON 還是已經變成外文的純文字，
    一律強制抽離英、日、韓文，只留下中文、數字、數量和常用符號。
    """
    if not items_raw_data:
        return "無餐點資料"
    
    # --- 第一道防線：如果原本是標準 JSON，就走精準中文提取 ---
    try:
        items_list = json.loads(items_raw_data) if isinstance(items_raw_data, str) else items_raw_data
        if isinstance(items_list, list):
            result_lines = []
            for index, item in enumerate(items_list):
                name_zh = item.get("name_zh", "未知商品")
                qty = item.get("qty", 1)
                item_line = f"{index + 1}. {name_zh} x {qty}"
                
                options_zh = item.get("options_zh", [])
                if options_zh and len(options_zh) > 0:
                    item_line += f" ({', '.join(options_zh)})"
                result_lines.append(item_line)
            return "\n".join(result_lines)
    except Exception:
        # 如果不是標準 JSON，代表是像你提供的那種已經變成外文純文字的字串，直接往下走第二道防線
        pass

    # --- 第二道防線：強力正則濾鏡（專治已經被轉成外文的純文字） ---
    text = str(items_raw_data)
    
    # 1. 抹除日文字元 (平假名、片假名)
    text = re.sub(r'[\u3040-\u309F\u30A0-\u30FF]', '', text)
    # 2. 抹除韓文字元
    text = re.sub(r'[\uAC00-\uD7A3\u1100-\u11FF]', '', text)
    # 3. 抹除英文字母 (保留用於數量的 'x' 或是 'X'，但前後通常帶數字)
    # 這裡我們精準一點：只刪除沒有和數字連在一起的純英文字母
    text = re.sub(r'(?<!\d)[a-zA-Z](?!\d)', '', text)
    
    # --- 整理因刪除文字而產生的雜亂符號 ---
    text = text.replace("()", "")            # 移除空的括號
    text = text.replace("(,)", "")
    text = re.sub(r',\s*,', ',', text)       # 把重複的逗號變成單個
    text = re.sub(r'\+\s*\+', '+', text)     # 把重複的加號變成單個
    text = re.sub(r'\s+', ' ', text)         # 多個空格變單個空格
    
    # 為了讓廚房好看，我們把多道菜之間的 " + " 變成「換行」，看起來就像列表！
    text = text.replace(" + ", "\n").replace("+", "\n")
    
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
                "items": parse_items_to_chinese_only(row[2]), # ⭕ 在這裡直接過濾成純中文文字！
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
        
        # 這裡同樣可以將排行需要的資料做中文化處理，或者直接回傳純文字
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
                "items": parse_items_to_chinese_only(row[2]), # ⭕ 歷史紀錄也一併在後端轉成乾淨的純中文！
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
