#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import time
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QPushButton, QLabel, QGroupBox, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QProgressBar, QStatusBar, QDateEdit, QDoubleSpinBox,
    QInputDialog, QStyledItemDelegate, QDialog, QDialogButtonBox,
    QCheckBox, QLineEdit, QColorDialog, QListWidget, QListWidgetItem,
    QFrame, QGridLayout, QSlider, QScrollArea, QSizePolicy, QMenu
)
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QCoreApplication, QPoint
from PySide6.QtGui import QFont, QKeyEvent, QColor, QAction, QPixmap
import pyqtgraph as pg
from pyqtgraph import DateAxisItem
import matplotlib.font_manager as fm
import requests
import hashlib

# ================== 全局配置 ==================
EXCHANGE_NAME = 'okx'
USE_PROXY = False
PROXY_URL = 'http://127.0.0.1:7897'
DEFAULT_TOP_N = 20
TIMEFRAME_MAP = {
    '1分钟': '1m', '5分钟': '5m', '15分钟': '15m',
    '1小时': '1h', '4小时': '4h', '日线': '1d'
}
INITIAL_CAPITAL = 1000.0
MAINTENANCE_MARGIN_RATE = 0.005

LEVERAGE_OPTIONS = [1, 3, 5, 6, 8, 10, 15, 20]
MAINSTREAM_SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']
CACHE_DIR = "data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
# =========================================

def get_cache_filename(symbol, timeframe, start_date, end_date):
    key = f"{symbol}_{timeframe}_{start_date}_{end_date}"
    hash_key = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{hash_key}.csv")

def save_to_cache(df, symbol, timeframe, start_date, end_date):
    try:
        filename = get_cache_filename(symbol, timeframe, start_date, end_date)
        df.to_csv(filename)
        print(f"数据已缓存: {filename}")
    except Exception as e:
        print(f"缓存失败: {e}")

def load_from_cache(symbol, timeframe, start_date, end_date):
    filename = get_cache_filename(symbol, timeframe, start_date, end_date)
    if os.path.exists(filename):
        try:
            df = pd.read_csv(filename, index_col=0, parse_dates=True)
            print(f"从缓存加载: {filename}")
            return df
        except Exception as e:
            print(f"读取缓存失败: {e}")
    return None

# ---------- 设置对话框 ----------
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        layout = QFormLayout(self)

        self.exchange_combo = QComboBox()
        self.exchange_combo.addItems(['okx', 'binance'])
        layout.addRow("交易所:", self.exchange_combo)

        self.use_proxy_cb = QCheckBox("使用代理")
        layout.addRow(self.use_proxy_cb)
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("http://127.0.0.1:7897")
        layout.addRow("代理地址:", self.proxy_edit)

        self.capital_spin = QDoubleSpinBox()
        self.capital_spin.setRange(0, 1e9)
        self.capital_spin.setDecimals(2)
        layout.addRow("默认本金 (USDT):", self.capital_spin)

        self.leverage_combo = QComboBox()
        self.leverage_combo.addItems([str(x) for x in LEVERAGE_OPTIONS])
        layout.addRow("默认杠杆:", self.leverage_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.load_settings()

    def load_settings(self):
        settings = QSettings("CryptoTrainer", "Settings")
        self.exchange_combo.setCurrentText(settings.value("exchange", EXCHANGE_NAME))
        self.use_proxy_cb.setChecked(settings.value("use_proxy", USE_PROXY, type=bool))
        self.proxy_edit.setText(settings.value("proxy_url", PROXY_URL))
        self.capital_spin.setValue(settings.value("initial_capital", INITIAL_CAPITAL, type=float))
        self.leverage_combo.setCurrentText(str(settings.value("leverage", "1")))

    def save_settings(self):
        settings = QSettings("CryptoTrainer", "Settings")
        settings.setValue("exchange", self.exchange_combo.currentText())
        settings.setValue("use_proxy", self.use_proxy_cb.isChecked())
        settings.setValue("proxy_url", self.proxy_edit.text())
        settings.setValue("initial_capital", self.capital_spin.value())
        settings.setValue("leverage", self.leverage_combo.currentText())

    def get_settings(self):
        return {
            'exchange': self.exchange_combo.currentText(),
            'use_proxy': self.use_proxy_cb.isChecked(),
            'proxy_url': self.proxy_edit.text(),
            'initial_capital': self.capital_spin.value(),
            'leverage': int(self.leverage_combo.currentText())
        }

# ---------- 中文字体设置 ----------
def setup_chinese_font(app):
    font_paths = [
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/arphic/uming.ttc',
    ]
    for path in font_paths:
        if os.path.exists(path):
            fm.fontManager.addfont(path)
            prop = fm.FontProperties(fname=path)
            font_name = prop.get_name()
            font = QFont(font_name, 10)
            app.setFont(font)
            print(f"使用中文字体: {font_name}")
            return True
    print("警告: 未找到中文字体，请安装: sudo apt install fonts-wqy-microhei")
    return False

# ---------- 数据获取线程（修复完整K线获取）----------
class DataFetchThread(QThread):
    data_ready = Signal(object)
    error = Signal(str)

    def __init__(self, symbol, timeframe, start_date, end_date, exchange, proxy):
        super().__init__()
        self.symbol = symbol
        self.timeframe = timeframe
        self.start_date = start_date
        self.end_date = end_date
        self.exchange = exchange
        self.proxy = proxy

    def run(self):
        cache_df = load_from_cache(self.symbol, self.timeframe,
                                   self.start_date.strftime('%Y-%m-%d'),
                                   self.end_date.strftime('%Y-%m-%d'))
        if cache_df is not None and len(cache_df) > 0:
            self.data_ready.emit(cache_df)
            return

        try:
            exchange_class = getattr(ccxt, self.exchange)
            config = {
                'enableRateLimit': True,
                'timeout': 30000,
                'options': {'defaultType': 'spot'}
            }
            if self.proxy:
                config['proxies'] = {'http': self.proxy, 'https': self.proxy}
            exchange = exchange_class(config)

            since = exchange.parse8601(self.start_date.strftime('%Y-%m-%dT00:00:00Z'))
            end_ts = exchange.parse8601(self.end_date.strftime('%Y-%m-%dT23:59:59Z'))

            timeframe_ms = exchange.parse_timeframe(self.timeframe) * 1000

            all_ohlcv = []
            max_retries = 3
            empty_count = 0

            while since < end_ts:
                ohlcv = None
                for attempt in range(max_retries):
                    try:
                        ohlcv = exchange.fetch_ohlcv(self.symbol, self.timeframe,
                                                     since=since, limit=1000)
                        empty_count = 0
                        break
                    except Exception as e:
                        if '429' in str(e) or 'rate limit' in str(e).lower():
                            wait_time = 5 * (attempt + 1)
                            print(f"请求限频，等待 {wait_time} 秒后重试...")
                            time.sleep(wait_time)
                        else:
                            print(f"请求失败 ({attempt+1}/{max_retries}): {e}")
                            time.sleep(2)
                        if attempt == max_retries - 1:
                            raise
                if ohlcv is None:
                    raise Exception(f"无法获取 {self.symbol} 的K线数据")

                if not ohlcv:
                    empty_count += 1
                    if empty_count > 3:
                        break
                    since += timeframe_ms
                    continue

                ohlcv = [c for c in ohlcv if c[0] <= end_ts]
                if not ohlcv:
                    break

                all_ohlcv.extend(ohlcv)

                last_ts = ohlcv[-1][0]
                since = last_ts + timeframe_ms
                if since > end_ts:
                    break

                time.sleep(0.5)

            if len(all_ohlcv) == 0:
                raise Exception("未获取到任何K线数据，请检查日期范围或网络")

            all_ohlcv = sorted(all_ohlcv, key=lambda x: x[0])
            unique = []
            last_ts = None
            for c in all_ohlcv:
                if last_ts is None or c[0] != last_ts:
                    unique.append(c)
                    last_ts = c[0]
            all_ohlcv = unique

            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df.sort_index(inplace=True)

            print(f"最终获取 {len(df)} 根K线")
            save_to_cache(df, self.symbol, self.timeframe,
                          self.start_date.strftime('%Y-%m-%d'),
                          self.end_date.strftime('%Y-%m-%d'))
            self.data_ready.emit(df)

        except Exception as e:
            self.error.emit(str(e))

# ---------- 热门币种线程 ----------
class TopCoinsThread(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, exchange, proxy):
        super().__init__()
        self.exchange = exchange
        self.proxy = proxy

    def run(self):
        try:
            exchange_class = getattr(ccxt, self.exchange)
            config = {'enableRateLimit': True}
            if self.proxy:
                config['proxies'] = {'http': self.proxy, 'https': self.proxy}
            exchange = exchange_class(config)
            tickers = exchange.fetch_tickers()
            gainers = []
            for symbol, data in tickers.items():
                if symbol.endswith('/USDT') and data.get('percentage') is not None:
                    gainers.append((symbol, data['percentage']))
            gainers.sort(key=lambda x: x[1], reverse=True)
            symbols = [sym for sym, _ in gainers[:DEFAULT_TOP_N]]
            self.finished.emit(symbols)
        except Exception as e:
            self.error.emit(str(e))

# ---------- 币种图标获取线程 ----------
class CoinIconFetcher(QThread):
    icons_ready = Signal(dict)

    def __init__(self, symbols_list, proxy=None):
        super().__init__()
        self.symbols_list = symbols_list
        self.proxy = proxy
        self._is_running = True

    def run(self):
        search_symbols = [s.replace('/USDT', '').upper() for s in self.symbols_list]
        proxies = {'http': self.proxy, 'https': self.proxy} if self.proxy else None
        url = 'https://api.coingecko.com/api/v3/coins/markets'
        params = {
            'vs_currency': 'usd',
            'order': 'market_cap_desc',
            'per_page': 250,
            'page': 1,
            'sparkline': 'false'
        }
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=15, proxies=proxies)
                if resp.status_code == 200:
                    data = resp.json()
                    break
                elif resp.status_code == 429:
                    wait = 3 * (attempt + 1)
                    print(f"API 限流，等待 {wait} 秒...")
                    time.sleep(wait)
                else:
                    raise Exception(f"HTTP {resp.status_code}")
            except Exception as e:
                print(f"获取 markets 列表失败 (尝试 {attempt+1}/3): {e}")
                if attempt == 2:
                    self.icons_ready.emit({})
                    return
                time.sleep(3)
        else:
            self.icons_ready.emit({})
            return

        image_map = {}
        for coin in data:
            symbol = coin['symbol'].upper()
            if symbol in search_symbols:
                image_map[symbol] = coin.get('image', '')
        icon_map = {}
        for full_symbol in self.symbols_list:
            if not self._is_running:
                break
            clean_symbol = full_symbol.replace('/USDT', '').upper()
            icon_url = image_map.get(clean_symbol)
            if icon_url:
                try:
                    img_resp = requests.get(icon_url, timeout=10, proxies=proxies)
                    if img_resp.status_code == 200:
                        pixmap = QPixmap()
                        pixmap.loadFromData(img_resp.content)
                        icon_map[full_symbol] = pixmap.scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                except Exception:
                    pass
        self.icons_ready.emit(icon_map)

    def stop(self):
        self._is_running = False
        self.quit()
        self.wait()

# ---------- 图标委托 ----------
class IconComboDelegate(QStyledItemDelegate):
    def __init__(self, icon_map, parent=None):
        super().__init__(parent)
        self.icon_map = icon_map

    def paint(self, painter, option, index):
        text = index.data()
        pixmap = self.icon_map.get(text)
        if pixmap and not pixmap.isNull():
            icon_rect = option.rect.adjusted(2, 2, -option.rect.width() + 22, -2)
            painter.drawPixmap(icon_rect, pixmap)
            text_rect = option.rect.adjusted(24, 0, 0, 0)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
        else:
            super().paint(painter, option, index)

# ---------- 水平线类 ----------
class HorizontalLine:
    def __init__(self, name, price, color='#F0B90B', style='--', visible=True):
        self.name = name
        self.price = price
        self.color = color
        self.style = style
        self.visible = visible
        self.item = None

class HorizontalLineManager:
    def __init__(self, plot_widget):
        self.plot_widget = plot_widget
        self.lines = []
    
    def add_line(self, name, price, color='#F0B90B', style='--', visible=True, label_text=None):
        line = HorizontalLine(name, price, color, style, visible)
        self.lines.append(line)
        if visible:
            self._draw_line(line, label_text)
        return line
    
    def _draw_line(self, line, label_text=None):
        if line.item:
            self.plot_widget.removeItem(line.item)
        pen = pg.mkPen(color=QColor(line.color), width=1, style=self._get_pen_style(line.style))
        label = label_text if label_text is not None else f"{line.price:.4f}"
        item = pg.InfiniteLine(pos=line.price, angle=0, pen=pen, label=label,
                               labelOpts={'position': 0.05, 'color': line.color, 'movable': True})
        self.plot_widget.addItem(item)
        line.item = item
    
    def _get_pen_style(self, style_str):
        if style_str == '-':
            return Qt.SolidLine
        elif style_str == '--':
            return Qt.DashLine
        elif style_str == '-.':
            return Qt.DashDotLine
        elif style_str == ':':
            return Qt.DotLine
        else:
            return Qt.SolidLine
    
    def update_line_visibility(self, line):
        if line.visible:
            self._draw_line(line)
        else:
            if line.item:
                self.plot_widget.removeItem(line.item)
                line.item = None
    
    def remove_line(self, line):
        if line.item:
            self.plot_widget.removeItem(line.item)
        self.lines.remove(line)
    
    def get_line_by_name(self, name):
        for line in self.lines:
            if line.name == name:
                return line
        return None
    
    def clear_all(self):
        for line in self.lines:
            if line.item:
                self.plot_widget.removeItem(line.item)
        self.lines.clear()

# ---------- 自定义X轴（时间轴）----------
class TimeAxisItem(DateAxisItem):
    def __init__(self, orientation='bottom', parent=None, timeframe='1d'):
        super().__init__(orientation, parent)
        self.timeframe = timeframe
        self.setStyle(showValues=True)
    
    def tickStrings(self, values, scale, spacing):
        strings = []
        for v in values:
            dt = datetime.fromtimestamp(v)
            if self.timeframe in ['1m', '5m', '15m']:
                strings.append(dt.strftime('%H:%M'))
            elif self.timeframe in ['1h', '4h']:
                strings.append(dt.strftime('%m-%d %H:%M'))
            else:
                strings.append(dt.strftime('%m-%d'))
        return strings

# ---------- 逐根K线训练画布（含MA5/10/20/30）----------
class KLineCanvas(pg.PlotWidget):
    def __init__(self, parent=None, timeframe='1d'):
        axis = TimeAxisItem(orientation='bottom', timeframe=timeframe)
        super().__init__(parent, axisItems={'bottom': axis})
        self.setBackground('#131722')
        self.showGrid(x=True, y=True, alpha=0.3)
        self.setLabel('left', '价格 (USDT)', color='white')
        self.setLabel('bottom', '日期', color='white')
        self.setTitle('', color='white')
        self.setMouseEnabled(x=True, y=True)
        
        self.candle_items = {}      # idx -> (wick, bar)
        self.close_line = None
        self.ma_curves = {}
        self.buy_scatter = None
        self.sell_scatter = None
        self.stop_scatter = None
        
        self.df = None
        self.symbol = ""
        self.timeframe = timeframe
        self.current_idx = -1       # 当前已解锁的最大索引（已显示的最大K线索引）
        self.trades = []
        self.visible_count = 50
        self.time_interval = 86400
        self.buffer_extra = 20
        self.simple_mode = False
        
        self.line_manager = HorizontalLineManager(self)
        
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.sigXRangeChanged.connect(self._on_view_range_changed)
    
    def set_data(self, df, symbol, timeframe, trades):
        self.df = df
        self.symbol = symbol
        self.timeframe = timeframe
        self.trades = trades
        self.current_idx = 0   # 只显示第0根K线
        if len(df) > 1:
            self.time_interval = (df.index[1] - df.index[0]).total_seconds()
        else:
            self.time_interval = 86400
        
        self.getAxis('bottom').timeframe = timeframe
        
        self.clear()
        self.candle_items.clear()
        self.close_line = None
        for curve in self.ma_curves.values():
            self.removeItem(curve)
        self.ma_curves.clear()
        self.line_manager.clear_all()
        
        self.simple_mode = False
        self._draw_single_candle(0)        # 绘制第一根K线
        self._update_view_range()          # 设置视图范围（当前K线在右侧）
        self.getAxis('bottom').setTickFont(QFont("Arial", 8))
        self._adjust_y_to_visible()
        self._update_ma()
        self._update_trades_markers()
        self.setTitle(f'{symbol} - {timeframe} K线训练营', color='white')
    
    def _draw_single_candle(self, idx):
        if idx in self.candle_items:
            return
        row = self.df.iloc[idx]
        o, h, l, c = row['open'], row['high'], row['low'], row['close']
        x_val = row.name.timestamp()
        if c >= o:
            color = '#26a69a'
        else:
            color = '#ef5350'
        wick = pg.PlotDataItem([x_val, x_val], [l, h], pen=pg.mkPen(color, width=1))
        self.addItem(wick)
        width = self.time_interval * 0.7
        if c >= o:
            height = c - o
            y0 = o
        else:
            height = o - c
            y0 = c
        bar = None
        if height > 0:
            bar = pg.BarGraphItem(x=[x_val], height=height, y0=y0, width=width, brush=color, pen=color)
            self.addItem(bar)
        self.candle_items[idx] = (wick, bar)
    
    def _remove_candle(self, idx):
        if idx not in self.candle_items:
            return
        wick, bar = self.candle_items[idx]
        self.removeItem(wick)
        if bar:
            self.removeItem(bar)
        del self.candle_items[idx]
    
    def _update_visible_candles(self, visible_min_idx, visible_max_idx):
        """只绘制已解锁（索引 <= current_idx）且在可见范围内的K线"""
        # 扩大范围，添加缓冲
        draw_min = max(0, visible_min_idx - self.buffer_extra)
        draw_max = min(len(self.df)-1, visible_max_idx + self.buffer_extra)
        # 限制最大绘制索引为 current_idx（不能显示未来K线）
        draw_max = min(draw_max, self.current_idx)
        visible_indices = list(range(visible_min_idx, visible_max_idx+1))
        visible_count = len([i for i in visible_indices if i <= self.current_idx])
        
        use_simple = visible_count > 200
        if use_simple != self.simple_mode:
            for idx in list(self.candle_items.keys()):
                self._remove_candle(idx)
            self.simple_mode = use_simple
        
        if self.simple_mode:
            # 简化模式：收盘价折线图
            unlocked_indices = [i for i in visible_indices if i <= self.current_idx]
            if unlocked_indices:
                xs = [self.df.index[i].timestamp() for i in unlocked_indices]
                ys = [self.df.iloc[i]['close'] for i in unlocked_indices]
                if self.close_line:
                    self.removeItem(self.close_line)
                self.close_line = self.plot(xs, ys, pen=pg.mkPen('#00ffaa', width=1), name='close')
            for idx in list(self.candle_items.keys()):
                self._remove_candle(idx)
        else:
            # 蜡烛图模式：绘制范围内的已解锁K线
            for i in range(draw_min, draw_max+1):
                if i <= self.current_idx and i not in self.candle_items:
                    self._draw_single_candle(i)
            to_remove = [idx for idx in self.candle_items.keys() if idx < draw_min or idx > draw_max]
            for idx in to_remove:
                self._remove_candle(idx)
            if self.close_line:
                self.removeItem(self.close_line)
                self.close_line = None
    
    def _update_ma(self):
        """基于已解锁的K线计算均线（只最近300根）"""
        for curve in self.ma_curves.values():
            self.removeItem(curve)
        self.ma_curves.clear()
        if self.current_idx < 0:
            return
        MAX_K = 300
        start_idx = max(0, self.current_idx - MAX_K + 1)
        drawn_df = self.df.iloc[start_idx:self.current_idx+1]
        if len(drawn_df) < 5:
            return
        closes = drawn_df['close'].values
        x_vals = [t.timestamp() for t in drawn_df.index]
        periods = [(5, '#f9a825', 'MA5'), (10, '#42a5f5', 'MA10'),
                   (20, '#ab47bc', 'MA20'), (30, '#26c6da', 'MA30')]
        for period, color, name in periods:
            if len(closes) < period:
                continue
            ma = pd.Series(closes).rolling(period).mean().values
            curve = self.plot(x_vals, ma, pen=pg.mkPen(color, width=1, style=Qt.DashLine), name=name)
            self.ma_curves[period] = curve
    
    def _update_trades_markers(self):
        if self.buy_scatter:
            self.removeItem(self.buy_scatter)
        if self.sell_scatter:
            self.removeItem(self.sell_scatter)
        if self.stop_scatter:
            self.removeItem(self.stop_scatter)
        buy_x, buy_y, sell_x, sell_y, stop_x, stop_y = [], [], [], [], [], []
        for trade in self.trades:
            trade_date = trade['date_obj'] if 'date_obj' in trade else pd.to_datetime(trade['date'])
            if trade_date in self.df.index:
                idx = self.df.index.get_loc(trade_date)
                if idx > self.current_idx:
                    continue
                x_val = self.df.index[idx].timestamp()
                if trade['side'] in ('开仓', '买入') and trade.get('direction') == '多':
                    buy_x.append(x_val)
                    buy_y.append(self.df['low'].iloc[idx] * 0.98)
                elif trade['side'] in ('开仓', '卖出') and trade.get('direction') == '空':
                    sell_x.append(x_val)
                    sell_y.append(self.df['high'].iloc[idx] * 1.02)
                elif trade['side'] in ('平仓', '平多', '平空', '止损'):
                    stop_x.append(x_val)
                    stop_y.append(self.df['high'].iloc[idx] * 1.05)
        if buy_x:
            self.buy_scatter = pg.ScatterPlotItem(buy_x, buy_y, brush=pg.mkBrush('#00ffaa'), size=10, symbol='t1', name='买入信号')
            self.addItem(self.buy_scatter)
        if sell_x:
            self.sell_scatter = pg.ScatterPlotItem(sell_x, sell_y, brush=pg.mkBrush('#ff5555'), size=10, symbol='t', name='卖出信号')
            self.addItem(self.sell_scatter)
        if stop_x:
            self.stop_scatter = pg.ScatterPlotItem(stop_x, stop_y, brush=pg.mkBrush('#ffaa00'), size=10, symbol='t', name='止损')
            self.addItem(self.stop_scatter)
    
    def _adjust_y_to_visible(self):
        if self.df is None:
            return
        x_range = self.viewRange()[0]
        left_ts, right_ts = x_range[0], x_range[1]
        left_dt = datetime.fromtimestamp(left_ts) if left_ts > 0 else self.df.index[0]
        right_dt = datetime.fromtimestamp(right_ts) if right_ts > 0 else self.df.index[-1]
        mask = (self.df.index >= left_dt) & (self.df.index <= right_dt) & (self.df.index <= self.df.index[self.current_idx])
        visible_df = self.df.loc[mask]
        if visible_df.empty:
            if self.candle_items:
                indices = sorted(self.candle_items.keys())
                visible_df = self.df.iloc[indices]
        if visible_df.empty:
            return
        y_min = visible_df['low'].min()
        y_max = visible_df['high'].max()
        if y_max > y_min:
            padding = (y_max - y_min) * 0.05
            self.setYRange(y_min - padding, y_max + padding)
    
    def _on_view_range_changed(self):
        if self.df is None:
            return
        x_range = self.viewRange()[0]
        left_ts, right_ts = x_range[0], x_range[1]
        left_idx = max(0, self.df.index.get_indexer([pd.to_datetime(left_ts, unit='s')], method='nearest')[0])
        right_idx = min(len(self.df)-1, self.df.index.get_indexer([pd.to_datetime(right_ts, unit='s')], method='nearest')[0])
        if left_idx < 0:
            left_idx = 0
        if right_idx < 0:
            right_idx = len(self.df)-1
        self._update_visible_candles(left_idx, right_idx)
        self._adjust_y_to_visible()
        self._update_ma()
        self._update_trades_markers()
    
    def _update_view_range(self):
        if self.current_idx < 0:
            return
        start_idx = max(0, self.current_idx - self.visible_count + 1)
        end_idx = self.current_idx
        left = self.df.index[start_idx].timestamp()
        right = self.df.index[end_idx].timestamp()
        self.setXRange(left, right, padding=0)
    
    def add_next_candle(self):
        next_idx = self.current_idx + 1
        if next_idx >= len(self.df):
            return False
        self.current_idx = next_idx
        # 绘制新K线（如果非简化模式）
        if not self.simple_mode:
            self._draw_single_candle(self.current_idx)
        # 移动视图，会触发 _on_view_range_changed 自动更新可见区域
        self._update_view_range()
        self.setTitle(f'{self.symbol} - {self.timeframe} K线训练营 (已显示{self.current_idx+1}/{len(self.df)}根)', color='white')
        return True
    
    def prev_candle(self):
        if self.current_idx <= 0:
            return False
        self.current_idx -= 1
        self._update_view_range()
        self.setTitle(f'{self.symbol} - {self.timeframe} K线训练营 (已显示{self.current_idx+1}/{len(self.df)}根)', color='white')
        return True
    
    def reset_chart(self):
        if self.df is None:
            return
        self.current_idx = 0
        self.clear()
        self.candle_items.clear()
        if self.close_line:
            self.removeItem(self.close_line)
            self.close_line = None
        for curve in self.ma_curves.values():
            self.removeItem(curve)
        self.ma_curves.clear()
        self.line_manager.clear_all()
        self.simple_mode = False
        self._draw_single_candle(0)
        self._update_view_range()
        self._adjust_y_to_visible()
        self._update_ma()
        self._update_trades_markers()
        self.setTitle(f'{self.symbol} - {self.timeframe} K线训练营 (已显示1/{len(self.df)}根)', color='white')
    
    def update_trades(self, trades):
        self.trades = trades
        self._update_trades_markers()
    
    def update_market_line(self, price):
        market_line = self.line_manager.get_line_by_name("市场价格")
        if market_line:
            market_line.price = price
            if market_line.visible:
                self.line_manager._draw_line(market_line, label_text=f"{price:.4f}")
        else:
            self.line_manager.add_line("市场价格", price, color="#00ffaa", style="-", visible=True, label_text=f"{price:.4f}")
    
    def add_position_lines(self, open_price, liquidation_price):
        entry_line = self.line_manager.get_line_by_name("开仓价")
        if entry_line:
            entry_line.price = open_price
            if entry_line.visible:
                self.line_manager._draw_line(entry_line, label_text=f"开仓 {open_price:.4f}")
        else:
            self.line_manager.add_line("开仓价", open_price, color="#ffaa00", style="-", visible=True, label_text=f"开仓 {open_price:.4f}")
        liq_line = self.line_manager.get_line_by_name("爆仓价")
        if liq_line:
            liq_line.price = liquidation_price
            if liq_line.visible:
                self.line_manager._draw_line(liq_line, label_text=f"爆仓 {liquidation_price:.4f}")
        else:
            self.line_manager.add_line("爆仓价", liquidation_price, color="#ff5555", style="--", visible=True, label_text=f"爆仓 {liquidation_price:.4f}")
    
    def remove_position_lines(self):
        entry_line = self.line_manager.get_line_by_name("开仓价")
        if entry_line:
            self.line_manager.remove_line(entry_line)
        liq_line = self.line_manager.get_line_by_name("爆仓价")
        if liq_line:
            self.line_manager.remove_line(liq_line)
    
    def show_context_menu(self, pos):
        menu = QMenu()
        predef_menu = QMenu("交易水平线", self)
        market_line = self.line_manager.get_line_by_name("市场价格")
        entry_line = self.line_manager.get_line_by_name("开仓价")
        liq_line = self.line_manager.get_line_by_name("爆仓价")
        if market_line:
            action = QAction("市场价格", self)
            action.setCheckable(True)
            action.setChecked(market_line.visible)
            action.triggered.connect(lambda checked: self.toggle_line_visibility(market_line))
            predef_menu.addAction(action)
        if entry_line:
            action = QAction("开仓价", self)
            action.setCheckable(True)
            action.setChecked(entry_line.visible)
            action.triggered.connect(lambda checked: self.toggle_line_visibility(entry_line))
            predef_menu.addAction(action)
        if liq_line:
            action = QAction("爆仓价", self)
            action.setCheckable(True)
            action.setChecked(liq_line.visible)
            action.triggered.connect(lambda checked: self.toggle_line_visibility(liq_line))
            predef_menu.addAction(action)
        if predef_menu.actions():
            menu.addMenu(predef_menu)
            menu.addSeparator()
        add_action = QAction("添加自定义水平线", self)
        add_action.triggered.connect(self.add_horizontal_line)
        menu.addAction(add_action)
        manage_action = QAction("管理所有水平线", self)
        manage_action.triggered.connect(self.manage_lines)
        menu.addAction(manage_action)
        menu.exec(self.mapToGlobal(pos))
    
    def add_horizontal_line(self):
        name, ok = QInputDialog.getText(self, "添加水平线", "线条名称:")
        if not ok or not name:
            return
        price, ok = QInputDialog.getDouble(self, "添加水平线", "价格:", 0, -1e9, 1e9, 4)
        if not ok:
            return
        color = QColorDialog.getColor()
        if not color.isValid():
            color = QColor(255, 255, 0)
        style, ok = QInputDialog.getItem(self, "线型", "选择线型:", ["-", "--", "-.", ":"], 1, False)
        if not ok:
            style = "--"
        self.line_manager.add_line(name, price, color.name(), style, visible=True, label_text=f"{price:.4f}")
    
    def manage_lines(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("水平线管理")
        layout = QVBoxLayout(dialog)
        list_widget = QListWidget()
        for line in self.line_manager.lines:
            item = QListWidgetItem(f"{line.name} ({line.price:.4f}) - {'可见' if line.visible else '隐藏'}")
            item.setData(Qt.UserRole, line)
            list_widget.addItem(item)
        layout.addWidget(list_widget)
        btn_layout = QHBoxLayout()
        edit_btn = QPushButton("编辑")
        delete_btn = QPushButton("删除")
        close_btn = QPushButton("关闭")
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(delete_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        
        def edit_line():
            current = list_widget.currentItem()
            if not current:
                return
            line = current.data(Qt.UserRole)
            name, ok = QInputDialog.getText(dialog, "编辑", "名称:", text=line.name)
            if ok:
                line.name = name
            price, ok = QInputDialog.getDouble(dialog, "编辑", "价格:", line.price, -1e9, 1e9, 4)
            if ok:
                line.price = price
            color = QColorDialog.getColor(QColor(line.color))
            if color.isValid():
                line.color = color.name()
            style, ok = QInputDialog.getItem(dialog, "线型", "选择线型:", ["-", "--", "-.", ":"], 0, False)
            if ok:
                line.style = style
            self.line_manager._draw_line(line, label_text=f"{line.price:.4f}")
            current.setText(f"{line.name} ({line.price:.4f}) - {'可见' if line.visible else '隐藏'}")
        
        def delete_line():
            current = list_widget.currentItem()
            if not current:
                return
            line = current.data(Qt.UserRole)
            self.line_manager.remove_line(line)
            list_widget.takeItem(list_widget.row(current))
        
        edit_btn.clicked.connect(edit_line)
        delete_btn.clicked.connect(delete_line)
        close_btn.clicked.connect(dialog.accept)
        dialog.exec()
    
    def toggle_line_visibility(self, line):
        line.visible = not line.visible
        self.line_manager.update_line_visibility(line)
    
    def delete_line(self, line):
        self.line_manager.remove_line(line)

# ---------- 收益曲线图 ----------
class EquityCurve(pg.PlotWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackground('#1E2329')
        self.showGrid(x=True, y=True, alpha=0.2)
        self.setLabel('left', '总资产 (USDT)', color='#EAECEF')
        self.setLabel('bottom', '交易事件序号', color='#EAECEF')
        self.setTitle('账户总资产曲线', color='#F0B90B')
        self.curve = self.plot(pen=pg.mkPen('#00b4b4', width=2))
        self.scatter = pg.ScatterPlotItem(brush=pg.mkBrush('#00b4b4'), size=5)
        self.addItem(self.scatter)
        self.history = []

    def add_point(self, total_asset):
        seq = len(self.history)
        self.history.append((seq, total_asset))
        xs = [p[0] for p in self.history]
        ys = [p[1] for p in self.history]
        self.curve.setData(xs, ys)
        self.scatter.setData(xs, ys)
        if len(ys) > 0:
            y_min = min(ys)
            y_max = max(ys)
            if y_max > y_min:
                padding = (y_max - y_min) * 0.1
                self.setYRange(y_min - padding, y_max + padding)
        if len(xs) > 1:
            self.setXRange(min(xs), max(xs))

    def clear_history(self):
        self.history.clear()
        self.curve.setData([], [])
        self.scatter.setData([], [])

# ---------- 持仓记录 ----------
class Position:
    def __init__(self, side, price, amount, leverage, margin):
        self.side = side
        self.price = price
        self.amount = amount
        self.leverage = leverage
        self.margin = margin
        self.high_since_buy = price if side == 'long' else None
        self.low_since_sell = price if side == 'short' else None
        self.liquidation_price = None

    def add_position(self, new_price, new_amount, new_margin):
        total_value = self.price * self.amount + new_price * new_amount
        self.amount += new_amount
        self.price = total_value / self.amount
        self.margin += new_margin
        if self.side == 'long':
            if new_price > self.high_since_buy:
                self.high_since_buy = new_price
        else:
            if new_price < self.low_since_sell:
                self.low_since_sell = new_price

# ---------- 主窗口 ----------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("加密货币K线策略复盘")
        self.setGeometry(100, 100, 1500, 850)

        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #0B0E11; color: #EAECEF; }
            QGroupBox { border: 1px solid #2B3139; border-radius: 4px; margin-top: 8px; font-weight: normal; background-color: #1E2329; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QPushButton { background-color: #2B3139; border: none; border-radius: 4px; padding: 5px; }
            QPushButton:hover { background-color: #3E454E; }
            QPushButton:pressed { background-color: #1E2329; }
            QComboBox { background-color: #2B3139; border: none; border-radius: 4px; padding: 4px; }
            QComboBox QAbstractItemView { background-color: #2B3139; selection-background-color: #3E454E; }
            QTableWidget { background-color: #0B0E11; alternate-background-color: #1E2329; gridline-color: #2B3139; }
            QHeaderView::section { background-color: #2B3139; padding: 4px; }
            QSlider::groove:horizontal { height: 4px; background: #2B3139; border-radius: 2px; }
            QSlider::handle:horizontal { background: #F0B90B; width: 12px; margin: -4px 0; border-radius: 6px; }
            QScrollArea { border: none; }
            QScrollBar:vertical { background: #1E2329; width: 8px; border-radius: 4px; }
            QScrollBar::handle:vertical { background: #2B3139; border-radius: 4px; min-height: 20px; }
            QDateEdit {
                background-color: #1E2329;
                border: 1px solid #2B3139;
                border-radius: 4px;
                padding: 2px;
                color: #EAECEF;
            }
            QDateEdit::drop-down {
                border: none;
                width: 20px;
                background-color: #2B3139;
                border-radius: 0 4px 4px 0;
            }
            QDateEdit QToolButton {
                background-color: #2B3139;
                color: #EAECEF;
                border: none;
                width: 20px;
            }
        """)

        # 账户拆分
        self.spot_balance = INITIAL_CAPITAL          # 资金账户余额
        self.contract_available = 0.0                # 合约账户可用余额
        self.initial_total_asset = INITIAL_CAPITAL   # 初始总资产
        self.position = None
        self.trades = []
        self.current_leverage = 1
        self.maintenance_rate = MAINTENANCE_MARGIN_RATE

        self.full_df = None
        self.current_idx = -1
        self.current_symbol = ""
        self.current_timeframe = ""

        # UI 构建
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4,4,4,4)
        main_layout.setSpacing(4)

        menubar = self.menuBar()
        settings_menu = menubar.addMenu("设置")
        settings_action = settings_menu.addAction("偏好设置")
        settings_action.triggered.connect(self.open_settings)

        # 添加视图菜单和全屏功能
        view_menu = menubar.addMenu("视图")
        fullscreen_action = QAction("全屏 (F11)", self)
        fullscreen_action.setShortcut("F11")
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fullscreen_action)

        # 控制栏
        control_layout = QHBoxLayout()
        self.coin_combo = QComboBox()
        self.coin_combo.setMinimumWidth(120)
        self.refresh_btn = QPushButton("刷新币种")
        self.period_combo = QComboBox()
        self.period_combo.addItems(list(TIMEFRAME_MAP.keys()))
        self.period_combo.setCurrentText("日线")
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(datetime.now() - timedelta(days=90))
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDate(datetime.now())
        self.load_btn = QPushButton("加载数据")
        self.next_btn = QPushButton("下一根K线")
        self.prev_btn = QPushButton("上一根K线")
        self.next_btn.setEnabled(False)
        self.prev_btn.setEnabled(False)
        self.reset_btn = QPushButton("重置账户")
        self.reset_btn.setEnabled(False)
        self.status_label = QLabel("就绪")
        self.progress = QProgressBar()
        self.progress.setVisible(False)

        for btn in [self.refresh_btn, self.load_btn, self.next_btn, self.prev_btn, self.reset_btn]:
            btn.setStyleSheet("background-color: #F0B90B; color: #0B0E11; font-weight: bold;")
        self.status_label.setStyleSheet("color: #EAECEF;")

        control_layout.addWidget(QLabel("币种:"))
        control_layout.addWidget(self.coin_combo)
        control_layout.addWidget(self.refresh_btn)
        control_layout.addWidget(QLabel("周期:"))
        control_layout.addWidget(self.period_combo)
        control_layout.addWidget(QLabel("开始:"))
        control_layout.addWidget(self.start_date)
        control_layout.addWidget(QLabel("结束:"))
        control_layout.addWidget(self.end_date)
        control_layout.addWidget(self.load_btn)
        control_layout.addWidget(self.prev_btn)
        control_layout.addWidget(self.next_btn)
        control_layout.addWidget(self.reset_btn)
        control_layout.addWidget(self.status_label)
        control_layout.addWidget(self.progress)
        control_layout.addStretch()
        main_layout.addLayout(control_layout)

        # 主体：左侧区域（K线图 + 当前持仓表格），右侧面板
        body_layout = QHBoxLayout()
        body_layout.setSpacing(4)

        # 左侧垂直布局
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0,0,0,0)
        left_layout.setSpacing(4)

        # K线画布
        self.current_timeframe_str = self.period_combo.currentText()
        self.canvas = KLineCanvas(timeframe=TIMEFRAME_MAP[self.current_timeframe_str])
        left_layout.addWidget(self.canvas, 3)

        # 当前持仓表格
        position_table_group = QGroupBox("当前持仓")
        pos_table_layout = QVBoxLayout()
        self.position_table = QTableWidget()
        self.position_table.setColumnCount(9)
        self.position_table.setHorizontalHeaderLabels([
            "交易对", "方向", "开仓均价", "当前价格", "强平价格", 
            "持仓数量", "保证金(USDT)", "未实现盈亏", "收益率"
        ])
        self.position_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.position_table.setAlternatingRowColors(True)
        self.position_table.setMaximumHeight(200)
        pos_table_layout.addWidget(self.position_table)
        position_table_group.setLayout(pos_table_layout)
        left_layout.addWidget(position_table_group)

        body_layout.addWidget(left_panel, 3)

        # 右侧面板
        right_panel = QWidget()
        right_panel.setFixedWidth(280)
        right_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0,0,0,0)
        right_layout.setSpacing(6)

        # 账户卡片（重点信息高亮）
        account_card = QGroupBox("账户")
        acc_layout = QGridLayout()
        acc_layout.setVerticalSpacing(2)
        acc_layout.setHorizontalSpacing(8)
        self.spot_label = QLabel(f"资金账户: {self.spot_balance:.2f} USDT")
        self.contract_label = QLabel(f"合约可用: {self.contract_available:.2f} USDT")
        self.position_label = QLabel("持仓: 无")
        self.position_margin_label = QLabel("保证金: 0.00 USDT")
        self.position_value_label = QLabel("市值: 0.00")
        self.position_pnl_label = QLabel("收益率: 0.00%")
        
        # 总资产：大号金色加粗
        self.total_asset_label = QLabel(f"总资产: {self.spot_balance + self.contract_available:.2f}")
        self.total_asset_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #F0B90B; background-color: #2B3139; border-radius: 4px; padding: 2px;")
        # 总盈亏：普通字体，但根据正负动态颜色
        self.pnl_label = QLabel("总盈亏: 0.00")
        # 总收益率：大号，根据正负变色
        self.pnl_percent_label = QLabel("总收益率: 0.00%")
        self.pnl_percent_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        
        acc_layout.addWidget(self.spot_label, 0, 0, 1, 2)
        acc_layout.addWidget(self.contract_label, 1, 0, 1, 2)
        acc_layout.addWidget(self.position_label, 2, 0)
        acc_layout.addWidget(self.position_margin_label, 2, 1)
        acc_layout.addWidget(self.position_value_label, 3, 0)
        acc_layout.addWidget(self.position_pnl_label, 3, 1)
        acc_layout.addWidget(self.total_asset_label, 4, 0, 1, 2)
        acc_layout.addWidget(self.pnl_label, 5, 0)
        acc_layout.addWidget(self.pnl_percent_label, 5, 1)
        account_card.setLayout(acc_layout)
        right_layout.addWidget(account_card)

        # 划转控件（增强：方向选择 + 百分比滑块）
        transfer_frame = QFrame()
        transfer_frame.setStyleSheet("background-color: #1E2329; border-radius: 4px; padding: 4px;")
        transfer_layout = QVBoxLayout(transfer_frame)
        transfer_layout.setContentsMargins(2,2,2,2)
        
        # 方向选择
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("划转方向:"))
        self.transfer_direction_combo = QComboBox()
        self.transfer_direction_combo.addItems(["资金 → 合约", "合约 → 资金"])
        self.transfer_direction_combo.currentTextChanged.connect(self.update_transfer_amount_by_percent)
        dir_layout.addWidget(self.transfer_direction_combo)
        transfer_layout.addLayout(dir_layout)
        
        # 金额输入与百分比滑块
        amount_layout = QHBoxLayout()
        self.transfer_amount_edit = QLineEdit()
        self.transfer_amount_edit.setPlaceholderText("金额")
        self.transfer_amount_edit.setFixedWidth(100)
        amount_layout.addWidget(QLabel("金额:"))
        amount_layout.addWidget(self.transfer_amount_edit)
        transfer_layout.addLayout(amount_layout)
        
        percent_layout = QHBoxLayout()
        percent_layout.addWidget(QLabel("百分比:"))
        self.transfer_percent_slider = QSlider(Qt.Horizontal)
        self.transfer_percent_slider.setRange(0, 100)
        self.transfer_percent_slider.setValue(0)
        self.transfer_percent_slider.valueChanged.connect(self.update_transfer_amount_by_percent)
        percent_layout.addWidget(self.transfer_percent_slider)
        self.transfer_percent_label = QLabel("0%")
        percent_layout.addWidget(self.transfer_percent_label)
        transfer_layout.addLayout(percent_layout)
        
        # 划转按钮
        btn_layout = QHBoxLayout()
        self.transfer_to_contract_btn = QPushButton("→ 合约")
        self.transfer_to_contract_btn.clicked.connect(self.transfer_to_contract)
        self.transfer_to_spot_btn = QPushButton("← 资金")
        self.transfer_to_spot_btn.clicked.connect(self.transfer_to_spot)
        btn_layout.addWidget(self.transfer_to_contract_btn)
        btn_layout.addWidget(self.transfer_to_spot_btn)
        transfer_layout.addLayout(btn_layout)
        
        right_layout.addWidget(transfer_frame)

        # 杠杆设置
        leverage_layout = QHBoxLayout()
        leverage_layout.addWidget(QLabel("杠杆:"))
        self.leverage_combo = QComboBox()
        self.leverage_combo.addItems([str(x) for x in LEVERAGE_OPTIONS])
        self.leverage_combo.setCurrentText("1")
        self.leverage_combo.currentTextChanged.connect(self.on_leverage_changed)
        leverage_layout.addWidget(self.leverage_combo)
        leverage_layout.addStretch()
        right_layout.addLayout(leverage_layout)

        # 当前价格
        self.current_price_label = QLabel("当前价格: --")
        self.current_price_label.setAlignment(Qt.AlignCenter)
        self.current_price_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #F0B90B; background-color: #1E2329; border-radius: 4px; padding: 4px;")
        right_layout.addWidget(self.current_price_label)

        # 开仓比例滑块
        ratio_layout = QVBoxLayout()
        ratio_layout.addWidget(QLabel("开仓比例 (%)"))
        self.ratio_slider = QSlider(Qt.Horizontal)
        self.ratio_slider.setRange(0, 100)
        self.ratio_slider.setValue(100)
        self.ratio_slider.valueChanged.connect(self.update_trade_preview)
        ratio_layout.addWidget(self.ratio_slider)
        self.ratio_value_label = QLabel("100%")
        self.ratio_value_label.setAlignment(Qt.AlignCenter)
        ratio_layout.addWidget(self.ratio_value_label)
        right_layout.addLayout(ratio_layout)

        # 买卖卡片
        trade_cards_layout = QHBoxLayout()
        trade_cards_layout.setSpacing(4)

        buy_frame = QFrame()
        buy_frame.setStyleSheet("background-color: #1E2329; border: 1px solid #2B3139; border-radius: 4px;")
        buy_layout = QVBoxLayout(buy_frame)
        buy_layout.setContentsMargins(4,4,4,4)
        buy_title = QLabel("买入 / 做多")
        buy_title.setStyleSheet("color: #00b4b4; font-weight: bold;")
        buy_layout.addWidget(buy_title)
        self.buy_margin_label = QLabel("保证金: 0.00 USDT")
        self.buy_amount_label = QLabel("可开: 0.0000")
        buy_layout.addWidget(self.buy_margin_label)
        buy_layout.addWidget(self.buy_amount_label)
        self.buy_btn = QPushButton("开多 / 加多")
        self.buy_btn.setStyleSheet("background-color: #00b4b4; color: white; font-weight: bold;")
        self.buy_btn.setEnabled(False)
        self.buy_btn.clicked.connect(lambda: self.open_position("做多"))
        buy_layout.addWidget(self.buy_btn)
        trade_cards_layout.addWidget(buy_frame)

        sell_frame = QFrame()
        sell_frame.setStyleSheet("background-color: #1E2329; border: 1px solid #2B3139; border-radius: 4px;")
        sell_layout = QVBoxLayout(sell_frame)
        sell_layout.setContentsMargins(4,4,4,4)
        sell_title = QLabel("卖出 / 做空")
        sell_title.setStyleSheet("color: #f6465d; font-weight: bold;")
        sell_layout.addWidget(sell_title)
        self.sell_margin_label = QLabel("保证金: 0.00 USDT")
        self.sell_amount_label = QLabel("可开: 0.0000")
        sell_layout.addWidget(self.sell_margin_label)
        sell_layout.addWidget(self.sell_amount_label)
        self.sell_btn = QPushButton("开空 / 加空")
        self.sell_btn.setStyleSheet("background-color: #f6465d; color: white; font-weight: bold;")
        self.sell_btn.setEnabled(False)
        self.sell_btn.clicked.connect(lambda: self.open_position("做空"))
        sell_layout.addWidget(self.sell_btn)
        trade_cards_layout.addWidget(sell_frame)

        right_layout.addLayout(trade_cards_layout)

        # 平仓比例滑块
        close_ratio_layout = QVBoxLayout()
        close_ratio_layout.addWidget(QLabel("平仓比例 (%)"))
        self.close_ratio_slider = QSlider(Qt.Horizontal)
        self.close_ratio_slider.setRange(0, 100)
        self.close_ratio_slider.setValue(100)
        self.close_ratio_slider.valueChanged.connect(self.update_close_preview)
        close_ratio_layout.addWidget(self.close_ratio_slider)
        self.close_ratio_value_label = QLabel("100%")
        self.close_ratio_value_label.setAlignment(Qt.AlignCenter)
        close_ratio_layout.addWidget(self.close_ratio_value_label)
        right_layout.addLayout(close_ratio_layout)

        # 平仓按钮
        self.close_btn = QPushButton("平仓")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.close_position_btn)
        self.close_btn.setStyleSheet("background-color: #f6465d; color: white; font-weight: bold;")
        right_layout.addWidget(self.close_btn)

        # 交易记录折叠
        trade_header = QHBoxLayout()
        trade_label = QLabel("交易记录")
        trade_label.setStyleSheet("font-weight: bold;")
        self.toggle_trade_btn = QPushButton("▼")
        self.toggle_trade_btn.setFixedSize(24,24)
        self.toggle_trade_btn.setStyleSheet("background-color: #2B3139;")
        self.toggle_trade_btn.clicked.connect(self.toggle_trade_table)
        trade_header.addWidget(trade_label)
        trade_header.addStretch()
        trade_header.addWidget(self.toggle_trade_btn)
        right_layout.addLayout(trade_header)

        self.trade_table = QTableWidget()
        self.trade_table.setColumnCount(5)
        self.trade_table.setHorizontalHeaderLabels(["日期","操作","价格","数量","金额"])
        self.trade_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.trade_table.setAlternatingRowColors(True)
        self.trade_table.setMaximumHeight(150)
        right_layout.addWidget(self.trade_table)

        # 资产曲线折叠
        equity_header = QHBoxLayout()
        equity_label = QLabel("资产曲线")
        equity_label.setStyleSheet("font-weight: bold;")
        self.toggle_equity_btn = QPushButton("▼")
        self.toggle_equity_btn.setFixedSize(24,24)
        self.toggle_equity_btn.setStyleSheet("background-color: #2B3139;")
        self.toggle_equity_btn.clicked.connect(self.toggle_equity_curve)
        equity_header.addWidget(equity_label)
        equity_header.addStretch()
        equity_header.addWidget(self.toggle_equity_btn)
        right_layout.addLayout(equity_header)

        self.equity_curve = EquityCurve()
        self.equity_curve.setMinimumHeight(150)
        right_layout.addWidget(self.equity_curve)

        right_layout.addStretch()
        body_layout.addWidget(right_panel)
        main_layout.addLayout(body_layout)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # 信号
        self.refresh_btn.clicked.connect(self.update_coin_list)
        self.load_btn.clicked.connect(self.load_data)
        self.next_btn.clicked.connect(self.next_candle)
        self.prev_btn.clicked.connect(self.prev_candle)
        self.reset_btn.clicked.connect(self.reset_account)

        self.load_settings()
        self.update_coin_list()
        self.icon_fetcher = None

    # ---------- 辅助方法 ----------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Right:
            self.next_candle()
        elif event.key() == Qt.Key_Left:
            self.prev_candle()
        elif event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
        else:
            super().keyPressEvent(event)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def load_settings(self):
        settings = QSettings("CryptoTrainer", "Settings")
        self.current_exchange = settings.value("exchange", EXCHANGE_NAME)
        self.use_proxy = settings.value("use_proxy", USE_PROXY, type=bool)
        self.proxy_url = settings.value("proxy_url", PROXY_URL)
        self.leverage_combo.setCurrentText(str(settings.value("leverage", "1")))
        new_capital = settings.value("initial_capital", INITIAL_CAPITAL, type=float)
        if new_capital != self.spot_balance + self.contract_available:
            self.spot_balance = new_capital
            self.contract_available = 0.0
            self.initial_total_asset = new_capital
            self.position = None
            self.trades = []
            self.equity_curve.clear_history()
            self.update_ui()
            self.record_equity()

    def on_leverage_changed(self, text):
        self.current_leverage = int(text)
        self.update_trade_preview()

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            settings = dialog.get_settings()
            QSettings("CryptoTrainer", "Settings").setValue("exchange", settings['exchange'])
            QSettings("CryptoTrainer", "Settings").setValue("use_proxy", settings['use_proxy'])
            QSettings("CryptoTrainer", "Settings").setValue("proxy_url", settings['proxy_url'])
            QSettings("CryptoTrainer", "Settings").setValue("initial_capital", settings['initial_capital'])
            QSettings("CryptoTrainer", "Settings").setValue("leverage", settings['leverage'])
            self.load_settings()
            self.update_coin_list()

    def update_coin_list(self):
        self.status_label.setText("获取币种...")
        self.refresh_btn.setEnabled(False)
        self.thread_top = TopCoinsThread(self.current_exchange, self.proxy_url if self.use_proxy else None)
        self.thread_top.finished.connect(self.on_top_coins_loaded)
        self.thread_top.error.connect(self.on_top_coins_error)
        self.thread_top.start()

    def on_top_coins_loaded(self, gainers):
        all_symbols = MAINSTREAM_SYMBOLS + gainers
        unique = []
        for s in all_symbols:
            if s not in unique:
                unique.append(s)
        self.coin_combo.clear()
        self.coin_combo.addItems(unique)
        self.status_label.setText("币种更新完成")
        self.refresh_btn.setEnabled(True)
        if self.icon_fetcher and self.icon_fetcher.isRunning():
            self.icon_fetcher.stop()
        self.icon_fetcher = CoinIconFetcher(unique, self.proxy_url if self.use_proxy else None)
        self.icon_fetcher.icons_ready.connect(self.set_coin_icons)
        self.icon_fetcher.start()

    def on_top_coins_error(self, err):
        self.status_label.setText(f"获取失败: {err}")
        self.refresh_btn.setEnabled(True)

    def set_coin_icons(self, icon_map):
        delegate = IconComboDelegate(icon_map, self.coin_combo)
        self.coin_combo.setItemDelegate(delegate)
        self.coin_combo.view().update()

    def load_data(self):
        symbol = self.coin_combo.currentText()
        if not symbol:
            self.status_label.setText("请选择币种")
            return
        timeframe = TIMEFRAME_MAP[self.period_combo.currentText()]
        start = self.start_date.date().toPython()
        end = self.end_date.date().toPython()
        if start >= end:
            self.status_label.setText("开始日期必须小于结束日期")
            return

        if self.position is not None and self.full_df is not None:
            last_price = self.full_df['close'].iloc[self.current_idx]
            side = "多仓" if self.position.side == 'long' else "空仓"
            reply = QMessageBox.question(self, "持仓检测", f"当前持有 {self.position.amount:.4f} 个 {side}，市价 {last_price:.4f}。\n是否自动平仓并切换币种？",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.close_all_positions(last_price)
            else:
                return

        self.status_label.setText(f"获取 {symbol} 数据...")
        self.load_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.thread_data = DataFetchThread(symbol, timeframe, start, end, self.current_exchange,
                                           self.proxy_url if self.use_proxy else None)
        self.thread_data.data_ready.connect(self.on_data_loaded)
        self.thread_data.error.connect(self.on_data_error)
        self.thread_data.start()

    def close_all_positions(self, price):
        if self.position is None:
            return
        amount = self.position.amount
        entry_price = self.position.price
        margin = self.position.margin
        if self.position.side == 'long':
            pnl = (price - entry_price) * amount
        else:
            pnl = (entry_price - price) * amount
        self.contract_available += margin + pnl
        side_str = "平多" if self.position.side == 'long' else "平空"
        self.trades.append({
            "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "date_obj": datetime.now(),
            "side": side_str,
            "direction": "多" if self.position.side == 'long' else "空",
            "price": price,
            "amount": amount,
            "total": amount * price
        })
        self.position = None
        self.canvas.remove_position_lines()
        self.update_ui()
        self.record_equity()

    def on_data_loaded(self, df):
        self.progress.setVisible(False)
        self.load_btn.setEnabled(True)
        self.status_label.setText("处理数据...")
        QCoreApplication.processEvents()

        self.full_df = df
        self.current_symbol = self.coin_combo.currentText()
        self.current_timeframe = TIMEFRAME_MAP[self.period_combo.currentText()]
        self.current_idx = 0

        self.canvas.timeframe = self.current_timeframe
        self.canvas.getAxis('bottom').timeframe = self.current_timeframe
        self.canvas.set_data(df, self.current_symbol, self.current_timeframe, self.trades)

        current_price = self.full_df['close'].iloc[self.current_idx]
        self.current_price_label.setText(f"当前价格: {current_price:.4f} USDT")
        self.canvas.update_market_line(current_price)
        self.update_ui()
        self.record_equity()
        self.update_trade_preview()

        self.next_btn.setEnabled(True)
        self.prev_btn.setEnabled(True)
        self.reset_btn.setEnabled(True)
        self.buy_btn.setEnabled(True)
        self.sell_btn.setEnabled(True)
        self.close_btn.setEnabled(True)

        self.status_label.setText(f"{self.current_symbol} 加载成功，共 {len(df)} 根K线")
        self.status_bar.showMessage("点击 → 前进，← 后退 | 右键图表管理水平线")
        self.status_label.repaint()

    def on_data_error(self, err):
        self.progress.setVisible(False)
        self.load_btn.setEnabled(True)
        self.status_label.setText(f"错误: {err}")

    def next_candle(self):
        if self.full_df is None:
            return
        success = self.canvas.add_next_candle()
        if not success:
            QMessageBox.information(self, "训练结束", "已经到达最后一根K线。")
            self.next_btn.setEnabled(False)
            return
        self.current_idx = self.canvas.current_idx
        current_price = self.full_df['close'].iloc[self.current_idx]
        self.current_price_label.setText(f"当前价格: {current_price:.4f} USDT")
        self.canvas.update_market_line(current_price)

        if self.position:
            if self.position.side == 'long':
                if current_price > self.position.high_since_buy:
                    self.position.high_since_buy = current_price
            else:
                if current_price < self.position.low_since_sell:
                    self.position.low_since_sell = current_price
        self.check_liquidation(current_price)

        self.update_ui()
        self.record_equity()
        self.update_trade_preview()
        if self.current_idx == len(self.full_df) - 1:
            self.next_btn.setEnabled(False)

    def prev_candle(self):
        if self.full_df is None:
            return
        success = self.canvas.prev_candle()
        if not success:
            QMessageBox.information(self, "提示", "已经是第一根K线")
            return
        self.current_idx = self.canvas.current_idx
        current_price = self.full_df['close'].iloc[self.current_idx]
        self.current_price_label.setText(f"当前价格: {current_price:.4f} USDT")
        self.canvas.update_market_line(current_price)
        self.update_ui()
        self.record_equity()
        self.update_trade_preview()
        self.next_btn.setEnabled(True)

    def check_liquidation(self, current_price):
        if self.position is None:
            return
        if self.position.side == 'long' and current_price <= self.position.liquidation_price:
            self.close_position(current_price, is_liquidation=True)
        elif self.position.side == 'short' and current_price >= self.position.liquidation_price:
            self.close_position(current_price, is_liquidation=True)

    def close_position(self, price, is_liquidation=False, close_ratio=1.0):
        if self.position is None:
            return
        amount = self.position.amount
        entry_price = self.position.price
        margin = self.position.margin
        reduce_amount = amount * close_ratio
        reduce_margin = margin * close_ratio
        if self.position.side == 'long':
            pnl = (price - entry_price) * reduce_amount
        else:
            pnl = (entry_price - price) * reduce_amount
        self.contract_available += reduce_margin + pnl
        reason = " (爆仓)" if is_liquidation else ""
        side_text = "平多" if self.position.side == 'long' else "平空"
        self.trades.append({
            "date": self.full_df.index[self.current_idx].strftime('%Y-%m-%d %H:%M:%S'),
            "date_obj": self.full_df.index[self.current_idx],
            "side": f"{side_text}{reason} ({close_ratio*100:.0f}%)",
            "direction": "多" if self.position.side == 'long' else "空",
            "price": price,
            "amount": reduce_amount,
            "total": reduce_amount * price
        })
        if close_ratio >= 1.0 or is_liquidation:
            self.position = None
            self.canvas.remove_position_lines()
        else:
            self.position.amount -= reduce_amount
            self.position.margin -= reduce_margin
        self.status_bar.showMessage(f"{side_text}{reason} {close_ratio*100:.0f}%，盈亏: {pnl:.2f} USDT")
        self.update_ui()
        self.record_equity()
        self.update_trade_preview()

    def close_position_btn(self):
        if self.full_df is None or self.current_idx < 0:
            QMessageBox.warning(self, "错误", "请先加载数据")
            return
        if self.position is None:
            QMessageBox.warning(self, "错误", "没有持仓")
            return
        price = self.full_df['close'].iloc[self.current_idx]
        if price == 0:
            QMessageBox.warning(self, "错误", "当前价格无效")
            return
        ratio = self.close_ratio_slider.value() / 100.0
        self.close_position(price, close_ratio=ratio)

    def update_trade_preview(self):
        if self.full_df is None or self.current_idx < 0:
            self.buy_margin_label.setText("保证金: 0.00 USDT")
            self.buy_amount_label.setText("可开: 0.0000")
            self.sell_margin_label.setText("保证金: 0.00 USDT")
            self.sell_amount_label.setText("可开: 0.0000")
            self.ratio_value_label.setText(f"{self.ratio_slider.value()}%")
            return
        price = self.full_df['close'].iloc[self.current_idx]
        ratio = self.ratio_slider.value() / 100.0
        leverage = self.current_leverage
        margin = self.contract_available * ratio
        contract_value = margin * leverage
        amount = contract_value / price if price > 0 else 0
        self.buy_margin_label.setText(f"保证金: {margin:.2f} USDT")
        self.buy_amount_label.setText(f"可开: {amount:.4f}")
        self.sell_margin_label.setText(f"保证金: {margin:.2f} USDT")
        self.sell_amount_label.setText(f"可开: {amount:.4f}")
        self.ratio_value_label.setText(f"{self.ratio_slider.value()}%")

    def update_close_preview(self):
        ratio = self.close_ratio_slider.value()
        self.close_ratio_value_label.setText(f"{ratio}%")
        if self.position:
            amount_to_close = self.position.amount * ratio / 100.0
            self.status_bar.showMessage(f"将平仓 {amount_to_close:.4f} 个 ({ratio}%)", 2000)

    def open_position(self, direction):
        if self.full_df is None or self.current_idx < 0:
            QMessageBox.warning(self, "错误", "请先加载数据")
            return
        price = self.full_df['close'].iloc[self.current_idx]
        if price <= 0:
            QMessageBox.warning(self, "错误", "价格无效")
            return
        ratio = self.ratio_slider.value() / 100.0
        leverage = self.current_leverage
        margin = self.contract_available * ratio
        if margin <= 0:
            QMessageBox.warning(self, "错误", "合约账户可用余额不足或比例太小")
            return
        contract_value = margin * leverage
        amount = contract_value / price
        if self.position is not None:
            if self.position.side == 'long' and direction == '做多':
                self.position.add_position(price, amount, margin)
                self.contract_available -= margin
                side_text = "加多"
            elif self.position.side == 'short' and direction == '做空':
                self.position.add_position(price, amount, margin)
                self.contract_available -= margin
                side_text = "加空"
            else:
                QMessageBox.warning(self, "错误", f"已有{self.position.side}持仓，方向相反无法加仓。请先平仓。")
                return
        else:
            self.position = Position('long' if direction == '做多' else 'short', price, amount, leverage, margin)
            self.contract_available -= margin
            side_text = "开多" if direction == '做多' else "开空"
            if direction == '做多':
                liq_price = price * (1 - 0.8 / leverage)
            else:
                liq_price = price * (1 + 0.8 / leverage)
            self.position.liquidation_price = liq_price
            self.canvas.add_position_lines(price, liq_price)
        self.trades.append({
            "date": self.full_df.index[self.current_idx].strftime('%Y-%m-%d %H:%M:%S'),
            "date_obj": self.full_df.index[self.current_idx],
            "side": side_text,
            "direction": direction,
            "price": price,
            "amount": amount,
            "total": margin
        })
        self.canvas.update_trades(self.trades)
        self.status_bar.showMessage(f"{side_text} {amount:.4f} 个，保证金 {margin:.2f} USDT")
        self.update_ui()
        self.record_equity()
        self.update_trade_preview()

    def reset_account(self):
        new_capital, ok = QInputDialog.getDouble(self, "重置账户", "请输入新的本金 (USDT):", self.spot_balance + self.contract_available, 0, 1e9, 2)
        if not ok:
            return
        self.spot_balance = new_capital
        self.contract_available = 0.0
        self.initial_total_asset = new_capital
        self.position = None
        self.trades = []
        self.equity_curve.clear_history()
        if self.full_df is not None:
            self.current_idx = 0
            self.canvas.reset_chart()
            current_price = self.full_df['close'].iloc[self.current_idx]
            self.current_price_label.setText(f"当前价格: {current_price:.4f} USDT")
            self.canvas.update_market_line(current_price)
            self.canvas.update_trades(self.trades)
        self.update_ui()
        self.record_equity()
        self.update_trade_preview()
        self.next_btn.setEnabled(True)
        self.prev_btn.setEnabled(True)
        self.status_bar.showMessage(f"账户已重置，本金设为 {new_capital:.2f}")

    def update_ui(self):
        # 显示资金账户和合约可用余额
        self.spot_label.setText(f"资金账户: {self.spot_balance:.2f} USDT")
        self.contract_label.setText(f"合约可用: {self.contract_available:.2f} USDT")
        # 计算总权益
        if self.position and self.full_df is not None and self.current_idx >= 0:
            current_price = self.full_df['close'].iloc[self.current_idx]
            if self.position.side == 'long':
                unrealized = (current_price - self.position.price) * self.position.amount
            else:
                unrealized = (self.position.price - current_price) * self.position.amount
            contract_equity = self.contract_available + self.position.margin + unrealized
        else:
            contract_equity = self.contract_available
        total_asset = self.spot_balance + contract_equity
        # 总资产高亮显示
        self.total_asset_label.setText(f"总资产: {total_asset:.2f}")
        total_pnl = total_asset - self.initial_total_asset
        self.pnl_label.setText(f"总盈亏: {total_pnl:.2f}")
        # 动态设置总盈亏颜色
        if total_pnl > 0:
            self.pnl_label.setStyleSheet("color: #00ffaa; font-weight: bold;")
        elif total_pnl < 0:
            self.pnl_label.setStyleSheet("color: #ff5555; font-weight: bold;")
        else:
            self.pnl_label.setStyleSheet("color: #EAECEF;")
        
        total_pnl_percent = (total_pnl / self.initial_total_asset) * 100 if self.initial_total_asset != 0 else 0
        self.pnl_percent_label.setText(f"总收益率: {total_pnl_percent:.2f}%")
        # 动态设置总收益率颜色和样式
        if total_pnl_percent > 0:
            self.pnl_percent_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #00ffaa;")
        elif total_pnl_percent < 0:
            self.pnl_percent_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #ff5555;")
        else:
            self.pnl_percent_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #EAECEF;")

        if self.position:
            pos_text = f"{self.position.amount:.4f} ({'多' if self.position.side=='long' else '空'})"
            self.position_label.setText(f"持仓: {pos_text}")
            self.position_margin_label.setText(f"保证金: {self.position.margin:.2f} USDT")
            if self.full_df is not None and self.current_idx >= 0:
                current_price = self.full_df['close'].iloc[self.current_idx]
                position_value = abs(self.position.amount) * current_price
                if self.position.side == 'long':
                    unrealized_pnl = (current_price - self.position.price) * self.position.amount
                else:
                    unrealized_pnl = (self.position.price - current_price) * self.position.amount
                pos_pnl_percent = (unrealized_pnl / self.position.margin) * 100 if self.position.margin != 0 else 0
                self.position_value_label.setText(f"市值: {position_value:.2f}")
                self.position_pnl_label.setText(f"收益率: {pos_pnl_percent:.2f}%")
                # 持仓收益率颜色
                if pos_pnl_percent > 0:
                    self.position_pnl_label.setStyleSheet("color: #00ffaa;")
                elif pos_pnl_percent < 0:
                    self.position_pnl_label.setStyleSheet("color: #ff5555;")
                else:
                    self.position_pnl_label.setStyleSheet("")
            else:
                self.position_value_label.setText("市值: 0.00")
                self.position_pnl_label.setText("收益率: 0.00%")
        else:
            self.position_label.setText("持仓: 无")
            self.position_margin_label.setText("保证金: 0.00 USDT")
            self.position_value_label.setText("市值: 0.00")
            self.position_pnl_label.setText("收益率: 0.00%")
            self.position_pnl_label.setStyleSheet("")  # 重置颜色

        # 更新当前持仓表格
        self.update_position_table()

        # 更新交易记录表格
        self.trade_table.setRowCount(len(self.trades))
        for i, t in enumerate(self.trades):
            self.trade_table.setItem(i, 0, QTableWidgetItem(t['date'].split()[0]))
            self.trade_table.setItem(i, 1, QTableWidgetItem(t['side']))
            self.trade_table.setItem(i, 2, QTableWidgetItem(f"{t['price']:.4f}"))
            self.trade_table.setItem(i, 3, QTableWidgetItem(f"{t['amount']:.4f}"))
            self.trade_table.setItem(i, 4, QTableWidgetItem(f"{t['total']:.2f}"))

    def update_position_table(self):
        self.position_table.setRowCount(0)
        if self.position is None or self.full_df is None or self.current_idx < 0:
            return
        current_price = self.full_df['close'].iloc[self.current_idx]
        if self.position.side == 'long':
            unrealized_pnl = (current_price - self.position.price) * self.position.amount
            roi = (unrealized_pnl / self.position.margin) * 100 if self.position.margin != 0 else 0
        else:
            unrealized_pnl = (self.position.price - current_price) * self.position.amount
            roi = (unrealized_pnl / self.position.margin) * 100 if self.position.margin != 0 else 0
        
        row = 0
        self.position_table.insertRow(row)
        self.position_table.setItem(row, 0, QTableWidgetItem(self.current_symbol))
        self.position_table.setItem(row, 1, QTableWidgetItem("多" if self.position.side == 'long' else "空"))
        self.position_table.setItem(row, 2, QTableWidgetItem(f"{self.position.price:.4f}"))
        self.position_table.setItem(row, 3, QTableWidgetItem(f"{current_price:.4f}"))
        self.position_table.setItem(row, 4, QTableWidgetItem(f"{self.position.liquidation_price:.4f}"))
        self.position_table.setItem(row, 5, QTableWidgetItem(f"{self.position.amount:.4f}"))
        self.position_table.setItem(row, 6, QTableWidgetItem(f"{self.position.margin:.2f}"))
        self.position_table.setItem(row, 7, QTableWidgetItem(f"{unrealized_pnl:.2f}"))
        self.position_table.setItem(row, 8, QTableWidgetItem(f"{roi:.2f}%"))
        for col in [7, 8]:
            item = self.position_table.item(row, col)
            if item:
                if unrealized_pnl >= 0:
                    item.setForeground(QColor("#00ffaa"))
                else:
                    item.setForeground(QColor("#ff5555"))

    def record_equity(self):
        if self.position and self.full_df is not None and self.current_idx >= 0:
            current_price = self.full_df['close'].iloc[self.current_idx]
            if self.position.side == 'long':
                unrealized = (current_price - self.position.price) * self.position.amount
            else:
                unrealized = (self.position.price - current_price) * self.position.amount
            contract_equity = self.contract_available + self.position.margin + unrealized
        else:
            contract_equity = self.contract_available
        total_asset = self.spot_balance + contract_equity
        self.equity_curve.add_point(total_asset)

    def toggle_trade_table(self):
        visible = not self.trade_table.isVisible()
        self.trade_table.setVisible(visible)
        self.toggle_trade_btn.setText("▲" if visible else "▼")

    def toggle_equity_curve(self):
        visible = not self.equity_curve.isVisible()
        self.equity_curve.setVisible(visible)
        self.toggle_equity_btn.setText("▲" if visible else "▼")

    # 划转功能（百分比辅助）
    def update_transfer_amount_by_percent(self):
        """根据当前百分比和方向，自动计算划转金额并填入金额输入框"""
        percent = self.transfer_percent_slider.value() / 100.0
        direction = self.transfer_direction_combo.currentText()
        if direction == "资金 → 合约":
            source_balance = self.spot_balance
        else:
            source_balance = self.contract_available
        amount = source_balance * percent
        self.transfer_amount_edit.setText(f"{amount:.2f}")
        self.transfer_percent_label.setText(f"{self.transfer_percent_slider.value()}%")

    def transfer_to_contract(self):
        """资金账户 -> 合约账户"""
        try:
            amount = float(self.transfer_amount_edit.text())
        except ValueError:
            QMessageBox.warning(self, "错误", "请输入有效数字")
            return
        if amount <= 0:
            QMessageBox.warning(self, "错误", "划转金额必须大于0")
            return
        if amount > self.spot_balance:
            QMessageBox.warning(self, "错误", "资金账户余额不足")
            return
        self.spot_balance -= amount
        self.contract_available += amount
        # 划转后重置百分比滑块和金额显示
        self.transfer_percent_slider.setValue(0)
        self.update_transfer_amount_by_percent()
        self.update_ui()
        self.record_equity()
        self.update_trade_preview()
        self.status_bar.showMessage(f"已从资金账户划转 {amount:.2f} USDT 至合约账户", 3000)

    def transfer_to_spot(self):
        """合约账户 -> 资金账户"""
        try:
            amount = float(self.transfer_amount_edit.text())
        except ValueError:
            QMessageBox.warning(self, "错误", "请输入有效数字")
            return
        if amount <= 0:
            QMessageBox.warning(self, "错误", "划转金额必须大于0")
            return
        if amount > self.contract_available:
            QMessageBox.warning(self, "错误", "合约账户可用余额不足")
            return
        self.contract_available -= amount
        self.spot_balance += amount
        self.transfer_percent_slider.setValue(0)
        self.update_transfer_amount_by_percent()
        self.update_ui()
        self.record_equity()
        self.update_trade_preview()
        self.status_bar.showMessage(f"已从合约账户划转 {amount:.2f} USDT 至资金账户", 3000)

if __name__ == "__main__":
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox"
    app = QApplication(sys.argv)
    setup_chinese_font(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())



    