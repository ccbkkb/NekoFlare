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
    "SUBDOMAINS": ["@", "www", "*"],  # Comma separated if using Env/Args
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
    Priority: Environment Variable > Command Line Argument > Default Value
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
    return [x.strip() for x in value.split(',') if x.strip()]

def get_best_ips(csv_path):
    """Reads CSV and returns IPs sorted by Speed (desc) and Latency (asc)."""
    ips = []
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
        
        # Sort: High Speed first, Low Latency second
        ips.sort(key=lambda x: (-x['speed'], x['latency']))
        return [x['ip'] for x in ips]
    except Exception as e:
        logging.error(f"Failed to read CSV: {e}")
        return []

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
        """Fetches all DNS records using pagination."""
        all_items = []
        skip = 0
        take = 100
        
        while True:
            try:
                params = {"take": take, "skip": skip}
                resp = requests.get(self.url, headers=self.headers, params=params)
                resp.raise_for_status()
                
                items = resp.json().get('items', [])
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

    def update_records(self, delete_list, add_list):
        """Executes batch delete followed by batch add."""
        # 1. Delete old records
        if delete_list:
            try:
                logging.info(f"Deleting {len(delete_list)} old records...")
                # Process in chunks to be safe
                chunk_size = 50
                for i in range(0, len(delete_list), chunk_size):
                    batch = delete_list[i:i + chunk_size]
                    requests.delete(self.url, headers=self.headers, json={"items": batch})
            except Exception as e:
                logging.error(f"Delete failed: {e}")

        # 2. Add new records
        if add_list:
            try:
                logging.info(f"Adding {len(add_list)} new records...")
                payload = {"force": True, "items": add_list}
                requests.put(self.url, headers=self.headers, json=payload)
            except Exception as e:
                logging.error(f"Add failed: {e}")

def main():
    # 1. Parse Arguments
    parser = argparse.ArgumentParser(description="Spaceship DNS Updater")
    parser.add_argument('--csv', help="Path to result.csv")
    parser.add_argument('--key', help="API Key")
    parser.add_argument('--secret', help="API Secret")
    parser.add_argument('--domain', help="Root Domain")
    parser.add_argument('--subs', help="Subdomains (comma separated)")
    parser.add_argument('--max', type=int, help="Max IPs to use")
    parser.add_argument('--ttl', type=int, help="TTL")
    args = parser.parse_args()

    # 2. Resolve Configuration (Env > Args > Default)
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
        logging.error("API Key and Secret are required.")
        sys.exit(1)

    # 3. Get IP List
    all_ips = get_best_ips(cfg["CSV"])
    if not all_ips:
        logging.error("No valid IPs found.")
        sys.exit(1)

    target_ips = all_ips[:min(len(all_ips), cfg["MAX"])]
    logging.info(f"Target IPs ({len(target_ips)}): {target_ips}")

    # 4. Process DNS
    client = SpaceshipDNS(cfg["DOMAIN"], cfg["KEY"], cfg["SECRET"], cfg["URL"])
    current_records = client.get_all_records()
    
    to_delete = []
    to_add = []

    for sub in cfg["SUBS"]:
        # Identify records to delete (Type A matching subdomain)
        for record in current_records:
            if record.get('type') == 'A' and record.get('name') == sub:
                to_delete.append(record)
        
        # Prepare records to add
        for ip in target_ips:
            to_add.append({
                "type": "A",
                "name": sub,
                "address": ip,
                "ttl": cfg["TTL"]
            })

    if not to_delete and not to_add:
        logging.info("No changes needed.")
    else:
        client.update_records(to_delete, to_add)
        logging.info("Update complete.")

if __name__ == "__main__":
    main()
