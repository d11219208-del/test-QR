from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import json
import re
import traceback
# 💡 請確保從你的專案結構中正確匯入 get_db_connection
# 假設 get_db_connection 在 database.py 中且在同級目錄：
from database import get_db_connection 

api_bp = Blueprint('api', __name__)

def get_tw_time_range():
    """ 輔助函式：取得台灣時間今日的 UTC 起訖時間範圍 """
    now_tw = datetime.utcnow() + timedelta(hours=8)
    start_tw = now_tw.replace(hour=0, minute=0, second=0, microsecond=0)
    end_tw = now_tw.replace(hour=23, minute=5, second=59, microsecond=999999)
    # 轉回 UTC 給資料庫查詢
    utc_start = start_tw - timedelta(hours=8)
    utc_end = end_tw - timedelta(hours=8)
    return utc_start, utc_end

def parse_items_to_chinese_only(items_raw_data):
    """ 當 content_json 無法解析時的第二道防線：過濾純外文字串 """
    try:
        if not items_raw_data or str(items_raw_data).strip() == "":
            return "無餐點資料"
        raw_str = str(items_raw_data).strip()
        backup_text = raw_str.replace(" + ", "\n").replace("+", "\n").strip()

        parsed_data = None
        if raw_str.startswith('[') or raw_str.startswith('{'):
            try:
                parsed_data = json.loads(raw_str)
                if isinstance(parsed_data, str) and (parsed_data.startswith('[') or parsed_data.startswith('{')):
                    parsed_data = json.loads(parsed_data)
            except Exception:
                pass

        if isinstance(parsed_data, dict):
            parsed_data = parsed_data.get("items", parsed_data.get("data", [parsed_data]))

        if isinstance(parsed_data, list):
            result_lines = []
            for index, item in enumerate(parsed_data):
                if isinstance(item, dict):
                    name_zh = item.get("name_zh") or item.get("name") or "未知商品"
                    qty = item.get("qty", 1)
                    line = f"{index + 1}. {name_zh} x {qty}"
                    opts = item.get("options_zh", [])
                    if opts and isinstance(opts, list):
                        line += f" ({', '.join(str(o) for o in opts)})"
                    result_lines.append(line)
                else:
                    result_lines.append(f"- {str(item)}")
            if result_lines:
                return "\n".join(result_lines)

        text = raw_str
        text = re.sub(r'[\u3040-\u309F\u30A0-\u30FF]', '', text)  # 拔除日文
        text = re.sub(r'[\uAC00-\uD7A3\u1100-\u11FF]', '', text)  # 拔除韓文
        text = re.sub(r'(?<!\d)[a-zA-Z](?!\d)', '', text)        # 拔除獨立英文
        text = text.replace("()", "").replace("(,)", "")
        text = re.sub(r',\s*,', ',', text)
        text = re.sub(r'\+\s*\+', '+', text)
        text = text.replace(" + ", "\n").replace("+", "\n").strip()
        
        remaining_content = re.sub(r'[\s\d(),+xX👍✨\n\-]', '', text)
        if len(remaining_content.strip()) == 0:
            return backup_text
            
        return text
    except Exception as e:
        return f"[過濾錯誤] {str(e)}"

# ─── 📱 1. 獲取待處理訂單 API ───
@api_bp.route('/orders/pending', methods=['GET'])
def get_pending_orders():
    try:
        utc_start, utc_end = get_tw_time_range()
        conn = get_db_connection()
        cur = conn.cursor()
        
        query = """
            SELECT id, table_number, items, total_price, status, created_at, lang, daily_seq, content_json,
                   customer_name, customer_phone, customer_address, scheduled_for, delivery_fee, order_type
            FROM orders 
            WHERE created_at >= %s AND created_at <= %s AND status = 'Pending'
            ORDER BY daily_seq ASC
        """
        try:
            cur.execute(query, (utc_start, utc_end))
        except Exception as e:
            conn.rollback()
            query_fallback = """
                SELECT id, table_number, items, total_price, status, created_at, lang, daily_seq, content_json,
                       customer_name, customer_phone, customer_address, scheduled_for, delivery_fee, 'unknown'
                FROM orders 
                WHERE created_at >= %s AND created_at <= %s AND status = 'Pending'
                ORDER BY daily_seq ASC
            """
            cur.execute(query_fallback, (utc_start, utc_end))

        orders = cur.fetchall()
        cur.close()
        conn.close()

        api_data_list = []
        for o in orders:
            oid, table, raw_items, total, status, created, order_lang, seq_num, c_json, \
            c_name, c_phone, c_addr, c_schedule, c_fee, c_type = o

            tw_time = created + timedelta(hours=8)
            tw_time_str = tw_time.strftime('%Y-%m-%d %H:%M:%S')

            items_final_text = ""
            try:
                if isinstance(c_json, str):
                    cart = json.loads(c_json)
                elif isinstance(c_json, (list, dict)):
                    cart = c_json if isinstance(c_json, list) else [c_json]
                else:
                    cart = []

                if cart:
                    lines = []
                    for index, item in enumerate(cart):
                        name = item.get('name_zh', item.get('name', '商品'))
                        qty = item.get('qty', 1)
                        options = item.get('options_zh', item.get('options', []))
                        
                        line = f"{index + 1}. {name} x {qty}"
                        if options and isinstance(options, list):
                            line += f" ({', '.join(options)})"
                        lines.append(line)
                    items_final_text = "\n".join(lines)
            except Exception:
                items_final_text = ""

            if not items_final_text.strip():
                items_final_text = parse_items_to_chinese_only(raw_items)

            api_data_list.append({
                "id": oid,
                "table_number": str(table).strip() if table else "外帶",
                "items": items_final_text,
                "total_price": int(total or 0),
                "status": status,
                "created_at": tw_time_str,
                "order_type": str(c_type).lower() if c_type else 'dine_in'
            })

        return jsonify({"success": True, "data": api_data_list})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e), "data": []}), 500

# ─── 📱 2. 修改訂單狀態 (接單/拒單) API ───
@api_bp.route('/orders/<int:order_id>/status', methods=['PUT'])
def update_order_status(order_id):
    try:
        data = request.get_json() or {}
        new_status = data.get('status') # 預期傳入 'Processing' (製作中) 或 'Cancelled'
        
        if not new_status:
            return jsonify({"success": False, "error": "缺少 status 參數"}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(
            "UPDATE orders SET status = %s WHERE id = %s RETURNING id", 
            (new_status, order_id)
        )
        updated_row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if updated_row:
            return jsonify({"success": True, "message": f"訂單 {order_id} 狀態已更新為 {new_status}"})
        else:
            return jsonify({"success": False, "error": "找不到該訂單"}), 404
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
