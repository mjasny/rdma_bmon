#!/usr/bin/env python3


from collections import deque
import time
import sys
import os
import atexit
import math
import re
import argparse
import csv


class CounterReader:
    def __init__(self, *paths):
        self._counters = {}
        for path in paths:
            for f in os.listdir(path):
                if os.path.isdir(f):
                    continue
                if f in self._counters:
                    raise Exception('Counter-Name not unique')
                self._counters[f] = os.path.join(path, f)

    def periodic(self, *, seconds=1):
        while True:
            start = time.time()
            yield self._read_all()
            end = time.time()
            time_to_sleep = seconds - (end-start)
            if time_to_sleep < 0:
                print('Warning: time_to_sleep negative', file=sys.stderr)
            time.sleep(time_to_sleep)

    def _read_all(self):
        return {k: self._read(v) for k, v in self._counters.items()}

    def _read(self, file):
        with open(file, 'r') as f:
            return eval(f.read())


def sizeof_fmt(num, suffix='B', precision=2):
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return f'{num:.{precision}f}{unit}{suffix}'  # 3.{precision}
        num /= 1024.0
    return f'{num:.1f}Yi{suffix}'


def unit_fmt(num, precision=2):
    for unit in ['', 'K', 'M', 'B', 'T']:
        if abs(num) < 1000.0:
            return f'{num:.{precision}f}{unit}'
        num /= 1000.0
    return f'{num:.1f}?'


class Diff:
    def __init__(self, *fields):
        self._fields = fields
        self._d = {}

    def feed(self, vals):
        diff = {k: vals[k] - self._d.get(k, vals[k]) for k in self._fields}
        self._d = {k: vals[k] for k in self._fields}
        return diff


def main(nic, port, interval, csv_file):
    HW_COUNTERS = '/sys/class/infiniband/{nic}/ports/{port}/hw_counters/'
    PORT_COUNTERS = '/sys/class/infiniband/{nic}/ports/{port}/counters/'

    counters = CounterReader(
        HW_COUNTERS.format(nic=nic, port=1),
        PORT_COUNTERS.format(nic=nic, port=1),
    )

    box = ['┏', '┓', '┗', '┛', '┃', '━', '┳', '┻', '┣', '╋', '┫']
    block = [' ', '▁', '▂', '▃', '▄', '▅', '▆', '▇', '█']

    cols, rows = os.get_terminal_size()

    sys.stdout.write('\033[?25l')  # hide cursor
    sys.stdout.flush()

    @atexit.register
    def cleanup():
        sys.stdout.write('\033[?25h')  # show cursor
        sys.stdout.flush()

    sys.stdout.write('\033[2J')  # clear and move to 0 0
    sys.stdout.flush()

    diff = Diff('port_rcv_data', 'port_xmit_data',
                'port_rcv_packets', 'port_xmit_packets')
    queue = deque(maxlen=cols//2-1)

    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    CC = '\033[0m'

    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def slen(s):
        return len(ansi_escape.sub('', s))

    csv_writer = None
    if csv_file is not None:
        f = open(csv_file, 'w')
        csv_writer = csv.DictWriter(f, diff._fields)
        csv_writer.writeheader()

    for vals in counters.periodic(seconds=interval):
        vals = {k: v*4 if k.endswith('_data') else v for k, v in vals.items()}
        vals = {k: v * (1/interval) for k, v in vals.items()}
        d = diff.feed(vals)

        if csv_file:
            csv_writer.writerow(d)

        lines = []
        lines.append(box[0] + box[5]*(cols-2) + box[1])

        # text = f'{d}'
        # lines.append(box[4] + text + ' '*(cols-2-len(text)) + box[4])

        text = f'{YELLOW}{"Interface":<28}{CC} │ {RED}{"RX bps":<10} {"pps":>10}{CC} │ {GREEN}{"TX bps":<10} {"pps":>10}{CC}'
        lines.append(box[4] + text + ' '*(cols-2-slen(text)) + box[4])
        text = f'{YELLOW}{nic:<28}{CC} │ {RED}{sizeof_fmt(d["port_rcv_data"]):>10} {unit_fmt(d["port_rcv_packets"]):>10}{CC} │ {GREEN}{sizeof_fmt(d["port_xmit_data"]):>10} {unit_fmt(d["port_xmit_packets"]):>10}{CC}'
        lines.append(box[4] + text + ' '*(cols-2-slen(text)) + box[4])

        text = f'{"─"*29}┴{"─"*23}┴{"─"*23}'
        lines.append(box[4] + text + '─'*(cols-2-len(text)) + box[4])

        queue.append(d)

        y = [x['port_xmit_data'] for x in queue]
        y2 = [x['port_rcv_data'] for x in queue]

        height = rows - len(lines) - 1
        try:
            y_factor = height / max(y)
        except ZeroDivisionError:
            y_factor = 0
        y = [x*y_factor for x in reversed(y)]
        bars = [[' ']*(cols-2) for _ in range(height)]

        try:
            y2_factor = height / max(y2)
        except ZeroDivisionError:
            y2_factor = 0
        y2 = [x*y2_factor for x in reversed(y2)]
        bars = [[' ']*(cols-2) for _ in range(height)]

        offset = cols-2 - 1
        for i, val in enumerate(y):
            i = offset - i
            whole_height = math.floor(val)
            remainder_height = (val) % 1
            part_height = math.floor(remainder_height * 8)
            part_char = block[part_height]

            for j in range(height):
                if j < whole_height:
                    bars[height-j-1][i] = block[-1]
                elif j == whole_height:
                    bars[height-j-1][i] = part_char
                else:
                    bars[height-j-1][i] = block[0]

        offset = (cols - 2) // 2 - 2
        for i, val in enumerate(y2):
            i = offset - i
            whole_height = math.floor(val)
            remainder_height = (val) % 1
            part_height = math.floor(remainder_height * 8)
            part_char = block[part_height]

            for j in range(height):
                if j < whole_height:
                    bars[height-j-1][i] = block[-1]
                elif j == whole_height:
                    bars[height-j-1][i] = part_char
                else:
                    bars[height-j-1][i] = block[0]

        offset = (cols - 2) // 2 - 1
        for j in range(height):
            bars[j][0] = RED + bars[j][0]
            bars[j][offset-1] += CC
            bars[j][offset] = ' '
            bars[j][offset+1] = GREEN + bars[j][offset+1]
            bars[j][len(bars[0])-1] += CC

        for b in bars:
            line = ''.join(b)
            lines.append(box[4] + line + ' '*(cols-2-len(line)) + box[4])

        for _ in range(rows-2-len(lines)):
            lines.append(box[4] + ' '*(cols-2) + box[4])

        lines.append(box[2] + box[5]*(cols-2) + box[3])

        # display frame buffer
        sys.stdout.write('\033[H')
        sys.stdout.write('\n'.join(lines))
        sys.stdout.flush()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RDMA Bandwidth Monitor')
    parser.add_argument('nic', type=str, default='mlx5_0',
                        help='NIC to monitor')
    parser.add_argument('-p', '--port', type=float, default=1, help='NIC port')
    parser.add_argument('-r', '--rate', type=float, default=0.25,
                        dest='interval', help='Refresh rate in seconds')
    parser.add_argument('--csv', dest='csv_file', type=str,
                        help='Export to CSV file')
    args = parser.parse_args()
    main(**vars(args))
