from flask import Blueprint, jsonify, request
from database import get_db_connection
from datetime import datetime

api_bp = Blueprint('api', __name__)

# ==========================================
# 1. 獲取所有「待處理 (Pending)」的訂單 (維持原樣)
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
                "items": row[2],
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
# 2. 變更訂單狀態 (支援：Processing / Cancelled 等)
# ==========================================
# 💡 註：這個不用動！因為我們原本就設計接收 data.get('status')。
# 當 Android 傳 {"status": "Processing"} 就是接單；傳 {"status": "Cancelled"} 就是拒絕！
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
# ✨ 新增 3. 區間營業報告 (ReportActivity 呼叫)
# ==========================================
# 讓 Android 傳入 start_date 與 end_date，計算該區間「已完成(Completed)」的總營業額與訂單數
@api_bp.route('/reports/revenue', methods=['GET'])
def get_revenue_report():
    start_date = request.args.get('start_date') # 格式: YYYY-MM-DD
    end_date = request.args.get('end_date')     # 格式: YYYY-MM-DD
    
    if not start_date or not end_date:
        return jsonify({"success": False, "message": "請提供 start_date 與 end_date"}), 400
        
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 💡 計算總營業額與總單數 (排除已取消或Pending的訂單)
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
# ✨ 新增 4. 銷售排行 (RankingActivity 呼叫)
# ==========================================
# 註：這裡假設你的 items 欄位在規模大時會拆獨立的 order_items 關聯表。
# 目前若先以文字存 items，為了方便你展示排行，後端可以撈出這段時間內所有訂單的 items 交給前端，或做簡單加總。
# 這裡先提供一個撈取指定時間內所有熱銷餐點資料的基礎 API。
@api_bp.route('/reports/ranking', methods=['GET'])
def get_sales_ranking():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # 撈取最近一個月已完成的訂單明細，用來給前端統計排行
        cur.execute("""
            SELECT items FROM orders 
            WHERE status = 'Completed' 
            ORDER BY created_at DESC LIMIT 50
        """)
        rows = cur.fetchall()
        items_list = [row[0] for row in rows]
        
        return jsonify({"success": True, "data": items_list}), 200
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()


# ==========================================
# ✨ 新增 5. 歷史訂單查詢 (HistoryActivity 呼叫)
# ==========================================
# 撈取所有非 Pending 的歷史紀錄 (Processing, Completed, Cancelled)
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
                "items": row[2],
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
