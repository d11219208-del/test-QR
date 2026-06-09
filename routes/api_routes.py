# routes/api_routes.py
from flask import Blueprint, jsonify, request
from database import get_db_connection

# 建立一個名為 'api' 的藍圖
api_bp = Blueprint('api', __name__)

# 1. 讓 Android App 獲取所有「待處理 (Pending)」的訂單
@api_bp.route('/orders/pending', methods=['GET'])
def get_pending_orders():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 撈取狀態為 Pending 的訂單，並依時間由舊到新排序（先來的先做）
        cur.execute("""
            SELECT id, table_number, items, total_price, status, created_at, order_type 
            FROM orders 
            WHERE status = 'Pending'
            ORDER BY created_at ASC
        """)
        rows = cur.fetchall()
        
        # 將資料包裝成 JSON 陣列
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

# 2. 讓 Android App 變更訂單狀態（例如：接單改為 Processing）
@api_bp.route('/orders/<int:order_id>/status', methods=['PUT'])
def update_order_status(order_id):
    # 從 Android 傳過來的 JSON 中取得新狀態
    data = request.get_json()
    new_status = data.get('status') # 例如 'Processing' 或 'Completed'
    
    if not new_status:
        return jsonify({"success": False, "message": "缺少 status 欄位"}), 400
        
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 更新資料庫
        cur.execute("UPDATE orders SET status = %s WHERE id = %s", (new_status, order_id))
        conn.commit()
        
        return jsonify({"success": True, "message": f"訂單 {order_id} 狀態已更新為 {new_status}"}), 200

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()
