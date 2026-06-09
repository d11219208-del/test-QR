from flask import Blueprint, jsonify, request
from database import get_db_connection
from datetime import datetime
import json  # 💡 引入 json 模組來解析餐點欄位

api_bp = Blueprint('api', __name__)

def parse_items_to_chinese_only(items_raw_data):
    """
    💡 後端核心過濾器：將包含多國語言的 JSON 字串，直接在後端淨化為純中文文字
    """
    if not items_raw_data:
        return "無餐點資料"
    
    try:
        # 如果資料庫撈出來的是字串，先轉成 Python 列表；如果是 dict/list 則直接用
        items_list = json.loads(items_raw_data) if isinstance(items_raw_data, str) else items_raw_data
        
        result_lines = []
        for index, item in enumerate(items_list):
            name_zh = item.get("name_zh", "未知商品")
            qty = item.get("qty", 1)
            
            # 組裝品名與數量： "1. 👍豬血湯 x 1"
            item_line = f"{index + 1}. {name_zh} x {qty}"
            
            # 處理客製化中文選項
            options_zh = item.get("options_zh", [])
            if options_zh and len(options_zh) > 0:
                options_str = ", ".join(options_zh)
                item_line += f" ({options_str})"
                
            result_lines.append(item_line)
            
        return "\n".join(result_lines) # 用換行符號連接每道菜
    except Exception as e:
        # 防呆：如果萬一解析失敗，返回原始資料
        return str(items_raw_data)


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
