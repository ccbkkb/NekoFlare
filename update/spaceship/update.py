import csv
import requests
import logging
import sys
import os
import argparse

# ================= Configuration =================

# Default Settings (Hardcoded)
DEFAULT_CONFIG = {
    "CSV_FILE": "result.csv",
    "API_KEY": "",
    "API_SECRET": "",
    "DOMAIN": "example.com",
    "SUBDOMAINS": ["@", "www", "*"],  # 默认的子域名列表
    "MAX_IP_COUNT": 2,
    "TTL": 300,
    "API_URL": "https://spaceship.dev/api/v1/dns/records"
}

# ================= Logic =================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def get_config_value(env_key, arg_val, default_val, cast_type=str):
    """
    优先级: 环境变量 > 命令行参数 > 默认值
    """
    val = os.getenv(env_key)
    if val is not None:
        return cast_type(val)
    if arg_val is not None:
        return cast_type(arg_val)
    return default_val

def parse_list(value):
    if isinstance(value, list):
        return value
    return[x.strip() for x in value.split(',') if x.strip()]

def get_best_ips(csv_path):
    """读取 CSV，按照速度(降序)和延迟(升序)排序并返回最优 IP"""
    ips = list()
    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    if not row.get('IP'): continue
                    ips.append({
                        "ip": row['IP'],
                        "latency": float(row['Latency']),
                        "speed": float(row['Speed'])
                    })
                except (ValueError, KeyError):
                    continue
        
        # 排序：速度越快越前，延迟越低越前
        ips.sort(key=lambda x: (-x['speed'], x['latency']))
        return [x['ip'] for x in ips]
    except Exception as e:
        logging.error(f"Failed to read CSV: {e}")
        return list()

class SpaceshipDNS:
    def __init__(self, domain, api_key, api_secret, base_url):
        self.domain = domain
        self.headers = {
            "X-API-Key": api_key,
            "X-API-Secret": api_secret,
            "Content-Type": "application/json"
        }
        self.url = f"{base_url}/{domain}"

    def get_all_records(self):
        """分页获取当前域名的所有自定义 DNS 记录"""
        all_items = list()
        skip = 0
        take = 100
        
        while True:
            try:
                params = {"take": take, "skip": skip}
                resp = requests.get(self.url, headers=self.headers, params=params)
                resp.raise_for_status()
                
                # 安全获取 items
                items = resp.json().get('items', list())
                if not items:
                    break
                    
                all_items.extend(items)
                if len(items) < take:
                    break
                skip += take
            except Exception as e:
                logging.error(f"Error fetching records: {e}")
                break
        return all_items

    def update_records_zero_downtime(self, delete_list, add_list):
        """
        零停机更新 (Zero Downtime Update):
        核心逻辑：先 ADD 新记录保障网络畅通，再 DELETE 淘汰旧记录。
        """
        
        # 步骤 1: 优先添加新记录 (PUT 追加)
        if add_list:
            try:
                logging.info(f"Step 1: Adding {len(add_list)} NEW records...")
                payload = {"force": True, "items": add_list}
                resp = requests.put(self.url, headers=self.headers, json=payload)
                resp.raise_for_status()
                logging.info("Successfully added new records. New IPs are active.")
            except requests.exceptions.RequestException as e:
                logging.error(f"Failed to add new records: {e}")
                if e.response is not None:
                    logging.error(f"API Error Details: {e.response.text}")
                
                # 严重安全防线：如果追加新 IP 失败，绝不执行删除操作，以防域名彻底断网
                logging.error("Aborting deletion of old records to maintain DNS availability.")
                return

        # 步骤 2: 删除过期记录 (DELETE 移除)
        if delete_list:
            try:
                logging.info(f"Step 2: Deleting {len(delete_list)} OLD records...")
                # Spaceship 的 DELETE 接口允许直接传入需要删除的对象数组
                resp = requests.delete(self.url, headers=self.headers, json=delete_list)
                resp.raise_for_status()
                logging.info("Successfully deleted old records. Seamless replacement complete!")
            except requests.exceptions.RequestException as e:
                logging.error(f"Failed to delete old records: {e}")
                if e.response is not None:
                    logging.error(f"API Error Details: {e.response.text}")

def main():
    # 1. 参数解析
    parser = argparse.ArgumentParser(description="Spaceship DNS Updater (Zero-Downtime)")
    parser.add_argument('--csv', help="Path to result.csv")
    parser.add_argument('--key', help="API Key")
    parser.add_argument('--secret', help="API Secret")
    parser.add_argument('--domain', help="Root Domain")
    parser.add_argument('--subs', help="Subdomains (comma separated)")
    parser.add_argument('--max', type=int, help="Max IPs to use")
    parser.add_argument('--ttl', type=int, help="TTL")
    args = parser.parse_args()

    # 2. 配置组装 (环境变量 > 命令行 > 默认值)
    cfg = {
        "CSV": get_config_value("CSV_FILE", args.csv, DEFAULT_CONFIG["CSV_FILE"]),
        "KEY": get_config_value("SPACESHIP_KEY", args.key, DEFAULT_CONFIG["API_KEY"]),
        "SECRET": get_config_value("SPACESHIP_SECRET", args.secret, DEFAULT_CONFIG["API_SECRET"]),
        "DOMAIN": get_config_value("DOMAIN", args.domain, DEFAULT_CONFIG["DOMAIN"]),
        "SUBS": parse_list(get_config_value("SUBDOMAINS", args.subs, DEFAULT_CONFIG["SUBDOMAINS"], cast_type=str)),
        "MAX": get_config_value("MAX_IP_COUNT", args.max, DEFAULT_CONFIG["MAX_IP_COUNT"], cast_type=int),
        "TTL": get_config_value("TTL", args.ttl, DEFAULT_CONFIG["TTL"], cast_type=int),
        "URL": DEFAULT_CONFIG["API_URL"]
    }

    if not cfg["KEY"] or not cfg["SECRET"]:
        logging.error("API Key and Secret are required. Please configure them.")
        sys.exit(1)

    # 3. 提取优质 IP 目标列表
    all_ips = get_best_ips(cfg["CSV"])
    if not all_ips:
        logging.error("No valid IPs found in CSV.")
        sys.exit(1)

    target_ips = all_ips[:min(len(all_ips), cfg["MAX"])]
    logging.info(f"Desired Target IPs ({len(target_ips)}): {target_ips}")

    # 4. 执行 DNS 比对分析
    client = SpaceshipDNS(cfg["DOMAIN"], cfg["KEY"], cfg["SECRET"], cfg["URL"])
    current_records = client.get_all_records()
    
    to_delete = list()
    to_add = list()

    # 针对每个子域名，计算出真正的差异 (Diff)
    for sub in cfg["SUBS"]:
        existing_ips = set()
        
        # 寻找当前线上已经存在的该子域名 A 记录 IP
        for record in current_records:
            if record.get('type') == 'A' and record.get('name') == sub:
                existing_ips.add(record.get('address'))
        
        desired_ips = set(target_ips)
        
        # 计算交集/差集：只提交全新出现的 IP
        for ip in (desired_ips - existing_ips):
            to_add.append({
                "type": "A",
                "name": sub,
                "address": ip,
                "ttl": cfg["TTL"]
            })
            
        # 计算交集/差集：只删除被淘汰的旧 IP
        for ip in (existing_ips - desired_ips):
            to_delete.append({
                "type": "A",
                "name": sub,
                "address": ip
            })

    # 5. 提交执行
    if not to_delete and not to_add:
        logging.info("DNS is already up-to-date. No changes needed.")
    else:
        client.update_records_zero_downtime(to_delete, to_add)

if __name__ == "__main__":
    main()
