from flask import Blueprint, jsonify, request
from datetime import timedelta
import json
import re
import traceback

api_bp = Blueprint('api', __name__)

# ─── 🛡️ 核心輔助工具：智慧留底與純文字過濾器 ───
def parse_items_to_chinese_only(items_raw_data):
    """
    當 content_json 無法解析時的第二道防線：過濾純外文字串
    """
    try:
        if not items_raw_data or str(items_raw_data).strip() == "":
            return "無餐點資料"

        raw_str = str(items_raw_data).strip()
        backup_text = raw_str.replace(" + ", "\n").replace("+", "\n").strip()

        # 1. 嘗試解開可能存在的雙重 JSON 字串
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

        # 2. 進行純文字正則過濾
        text = raw_str
        text = re.sub(r'[\u3040-\u309F\u30A0-\u30FF]', '', text)  # 拔除日文假名
        text = re.sub(r'[\uAC00-\uD7A3\u1100-\u11FF]', '', text)  # 拔除韓文
        text = re.sub(r'(?<!\d)[a-zA-Z](?!\d)', '', text)        # 拔除獨立英文
        
        text = text.replace("()", "").replace("(,)", "")
        text = re.sub(r',\s*,', ',', text)
        text = re.sub(r'\+\s*\+', '+', text)
        text = text.replace(" + ", "\n").replace("+", "\n").strip()
        
        # 3. 檢查過濾後是否只剩下空白或符號（代表是純外文單，如純韓文）
        remaining_content = re.sub(r'[\s\d(),+xX👍✨\n\-]', '', text)
        if len(remaining_content.strip()) == 0:
            return backup_text  # 觸發智慧留底，回傳原外文
            
        return text

    except Exception as e:
        return f"[過濾錯誤] {str(e)}"


# ─── 📱 Android App 專用：獲取待處理訂單 API ───
@api_bp.route('/orders/pending', methods=['GET'])
def get_pending_orders():
    try:
        # 1. 取得台灣時間的今日起訖時間 (轉換為 UTC 時間以便與資料庫比對)
        utc_start, utc_end = get_tw_time_range()

        # 2. 建立資料庫連線
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 3. 主要 SQL 查詢：同步 kitchen_routes.py 的 15 個欄位與排序邏輯
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
            # 🔄 降級方案 (Fallback)：若資料庫缺 order_type 欄位，自動補上 'unknown' 防止崩潰
            conn.rollback()
            print(f"SQL Fallback triggered (api_pending_orders): {e}")
            query_fallback = """
                SELECT id, table_number, items, total_price, status, created_at, lang, daily_seq, content_json,
                       customer_name, customer_phone, customer_address, scheduled_for, delivery_fee, 'unknown'
                FROM orders 
                WHERE created_at >= %s AND created_at <= %s AND status = 'Pending'
                ORDER BY daily_seq ASC
            """
            cur.execute(query_fallback, (utc_start, utc_end))

        orders = cur.fetchall()
        conn.close()

        # 4. 逐筆打包為 Android 專用 JSON 格式
        api_data_list = []
        for o in orders:
            # 完整解包 15 個變數，確保結構與 kitchen 一致
            oid, table, raw_items, total, status, created, order_lang, seq_num, c_json, \
            c_name, c_phone, c_addr, c_schedule, c_fee, c_type = o

            # 🕒 時間對齊：與 kitchen 一樣，將資料庫 UTC 轉回台灣時間字串
            tw_time = created + timedelta(hours=8)
            tw_time_str = tw_time.strftime('%Y-%m-%d %H:%M:%S')

            # 🥢 商品明細核心解析 (優先使用結構完整的 content_json)
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
                        name = item.get('name_zh', item.get('name', '商品'))  # 優先抓中文名
                        qty = item.get('qty', 1)
                        options = item.get('options_zh', item.get('options', []))
                        
                        line = f"{index + 1}. {name} x {qty}"
                        if options and isinstance(options, list):
                            line += f" ({', '.join(options)})"
                        lines.append(line)
                    items_final_text = "\n".join(lines)
            except Exception:
                items_final_text = ""

            # 🛡️ 備用防線：如果 content_json 解析出來是空的，就啟用智慧純文字過濾器
            if not items_final_text.strip():
                items_final_text = parse_items_to_chinese_only(raw_items)

            # 🍱 封裝成 Android 端需要的 Model 格式 (對應你的 Order.java)
            api_data_list.append({
                "id": oid,
                "table_number": str(table).strip() if table else "外帶",
                "items": items_final_text,  # 🌟 完美的純文字排版，絕不為空
                "total_price": int(total or 0),
                "status": status,
                "created_at": tw_time_str,
                "order_type": str(c_type).lower() if c_type else 'dine_in'
            })

        return jsonify({
            "success": True,
            "data": api_data_list
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e),
            "data": []
        }), 500
