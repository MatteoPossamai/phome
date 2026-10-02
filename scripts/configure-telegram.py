#!/usr/bin/env python3
"""Phone/Termux: private Telegram setup and Alertmanager config rendering."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path.home() / 'phome'


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(text)
    temporary.replace(path)


def render(root=ROOT):
    config = json.loads((root / 'config/alertmanager.json').read_text())
    secrets = root / 'data/telegram'
    if (secrets / 'chat.json').exists():
        chat = json.loads((secrets / 'chat.json').read_text())['chat_id']
        if isinstance(chat, bool) or not isinstance(chat, int) or not chat:
            raise ValueError('Invalid Telegram chat ID')
        token = (secrets / 'bot-token').read_text().strip()
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}', token):
            raise ValueError('Invalid Telegram token file')
        config['route']['receiver'] = 'telegram'
        config['receivers'] = [{
            'name': 'telegram',
            'telegram_configs': [{
                'bot_token_file': '/opt/phome/data/telegram/bot-token',
                'chat_id': chat,
                'send_resolved': True,
                'parse_mode': 'HTML',
                'message': '{{ template "phome.telegram" . }}',
            }],
        }]
    path = root / 'data/alertmanager/config.json'
    value = json.dumps(config, indent=2) + '\n'
    if not path.exists() or path.read_text() != value:
        private_write(path, value)
    return path


def telegram(token, method):
    request = urllib.request.Request('https://api.telegram.org/bot' + token + '/' + method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise ValueError(f'Telegram rejected {method} (HTTP {error.code}); check the token and bot setup') from None
    except (OSError, ValueError):
        raise ValueError('Telegram request failed; check internet access and retry') from None
    if not result.get('ok'):
        raise ValueError('Telegram did not accept the request')
    return result['result']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true', help='Render config only; never prompt')
    parser.add_argument('--reload', action='store_true', help='Render and reload the running Alertmanager')
    args = parser.parse_args()
    if not args.render and not args.reload:
        if not sys.stdin.isatty():
            raise ValueError('Run interactively in Termux or ssh -t; the token prompt must be hidden')
        token = getpass.getpass('Telegram bot token (hidden): ').strip()
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}', token):
            raise ValueError('Unexpected token format')
        telegram(token, 'getMe')
        updates = telegram(token, 'getUpdates')
        chats = {}
        for update in updates:
            message = update.get('message', {})
            chat = message.get('chat', {})
            if chat.get('type') == 'private' and isinstance(chat.get('id'), int):
                chats[chat['id']] = chat
        if not chats:
            raise ValueError('No private chat found. Open your bot, send /start, then retry')
        if len(chats) == 1:
            chat_id = next(iter(chats))
        else:
            for chat_id, chat in chats.items():
                print(chat_id, chat.get('username', chat.get('first_name', 'private chat')))
            chat_id = int(input('Destination chat ID from the list: '))
            if chat_id not in chats:
                raise ValueError('Choose one of the listed chats')
        private_write(ROOT / 'data/telegram/bot-token', token + '\n')
        private_write(ROOT / 'data/telegram/chat.json', json.dumps({'chat_id': chat_id}) + '\n')
    render()
    if not args.render:
        subprocess.run(['proot-distro', 'login', '--bind', str(ROOT) + ':/opt/phome',
                        'debian', '--', '/usr/bin/amtool', 'check-config',
                        '/opt/phome/data/alertmanager/config.json'], check=True)
        request = urllib.request.Request('http://127.0.0.1:9093/-/reload', data=b'', method='POST')
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
        except OSError:
            raise ValueError('Configuration saved; Alertmanager reload failed. Check the service and retry --reload') from None
        print('Telegram configuration saved privately and Alertmanager reloaded.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        # Do not print request URLs or exception chains containing the bot token.
        if isinstance(error, ValueError):
            print(str(error), file=sys.stderr)
        else:
            print('Setup failed; check private files and installed commands.', file=sys.stderr)
        sys.exit(1)
