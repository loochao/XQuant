# -*- coding: utf-8 -*-

"""
Portfolio抽象基类/类
头寸跟踪、订单管理、风险/收益分析等
TODO: 可以大大扩展

SignalEvent -> Portfolio -> OrderEvent
                         <- FillEvent
    处理Signla，产生Order，翻译Fill以更新仓位

可以看出，Portfolio是最复杂的部分，各种Event可以与之交互

@author: X0Leon
@version: 0.1
"""

import datetime
import numpy as np
import pandas as pd
import queue

from abc import ABCMeta, abstractmethod
from math import floor # 返回下舍整数值

from event import OrderEvent, FillEvent

class Portfolio(object):
    """
    Portofio类处理头寸和持仓市值
    基本bar来计算，可以是秒、分钟、5分钟、30分钟、60分钟等的K线
    """
    __metaclass__ = ABCMeta

    @abstractmethod
    def update_signal(self, event):
        """
        基于portfolio的管理逻辑，使用SignalEvent产生新的orders
        """
        raise NotImplementedError("未实现update_signal()，此方法是必须的！")

    @abstractmethod
    def update_fill(self, event):
        """
        从FillEvent中更新组合当前的头寸和持仓市值
        """
        raise NotImplementedError("未实现update_fill()，此方法是必须的！")


# 一个简单的组合订单管理的类
class NaivePortfolio(Portfolio):
    """
    NaivePortfolio发送orders给brokerage对象，这里简单地使用固定的数量，
    不进行任何风险管理或仓位管理（这是不现实的！），仅供测试使用
    """
    def __init__(self, bars, events, start_date, initial_capital=1.0e5):
        """
        使用bars和event队列初始化portfolio，同时包含其实时间和初始资本
        参数：
        bars: DataHandler对象，使用当前市场数据
        events: Event queue对象
        start_date: 组合其实的时间，实际上就是指某个k线
        initial_capital: 起始的资本
        """
        self.bars = bars
        self.events = events
        self.symbol_list = self.bars.symbol_list
        self.start_date = start_date
        self.initial_capital = initial_capital

        self.all_positions = self.construct_all_positions() # 字典列表
        self.current_postitions = dict((k,v) for k,v in [(s,0) for s in self.symbol_list]) # 字典

        self.all_holdings = self.construct_all_holdings() # 字典列表
        self.current_holdings = self.construct_current_holdings() # 字典

    def construct_all_positions(self):
        """
        构建头寸列表，其元素为通过字典解析产生的字典，每个symbol键的值为零
        且额外加入了datetime键
        """
        d = dict((k,v) for k,v in [(s,0) for s in self.symbol_list])
        d['datetime'] = self.start_date
        return [d]

    def construct_all_holdings(self):
        """
        构建全部持仓市值
        包括现金、累计费率和合计值的键
        """
        d = dict((k,v) for k,v in [(s,0) for s in self.symbol_list])
        d['datetime'] = self.start_date
        d['cash'] = self.initial_capital
        d['commission'] = 0.0
        d['total'] = self.initial_capital
        return [d]

    def construct_current_holdings(self):
        """
        构建当前持仓市值
        和construct_all_holdings()唯一不同的是返回字典，而非字典的列表
        """
        d = dict((k,v) for k,v in [(s,0) for s in self.symbol_list])
        d['datetime'] = self.start_date
        d['cash'] = self.initial_capital
        d['commission'] = 0.0
        d['total'] = self.initial_capital
        return d

    ######################  “市场的脉搏” ##############################################
    # 市场发生交易，我们需要更新持仓市值：1）实时交易可以解析交易商的数据；
    # 2）回测时采取模拟的方法，这里用上一根k线的收盘价*头寸，这对于日内交易相对较为准确

    def update_timeindex(self, event):
        """
        用于追踪新的持仓市值
        向持仓头寸中加入新的纪录，也就是刚结束的这根完整k bar
        从events队列中使用MarketEvent
        """
        bars = {}
        for sym in self.symbol_list:
            bars[sym] = self.bars.get_latest_bars(sym, N=1)
        # 更新头寸，字典
        dp = dict((k,v) for k,v in [(s,0) for s in self.symbol_list])
        dp['datetime'] = bars[self.symbol_list[0]][0][1]

        for s in self.symbol_list:
            dp[s] = self.current_postitions[s]
        # 添加当前头寸
        self.all_positions.append(dp) # 注意all_postions是k bar周期的字典列表
        # 更新持仓，字典
        dh = dict((k,v) for k,v in [(s,0) for s in self.symbol_list])
        dh['datetime'] = bars[self.symbol_list[0]][0][1]
        dh['cash'] =  self.current_holdings['cash']
        dh['commission'] = self.current_holdings['commission']
        dh['total'] = self.current_holdings['total']

        for s in self.symbol_list:
            # 估计持仓市值
            market_value = self.current_postitions[s] * bars[s][0][5]
            dh[s] = market_value
            dh['total'] += market_value

        self.all_holdings.append(dh)

     
    # (1) 与FillEvent对象交互: 通过两个工具函数来实现Portofio抽象基类的update_fill()

    def update_position_from_fill(self, fill):
        """
        从FillEvent对象中读取数据以更新头寸position
        参数：
        fill: FillEvent对象
        """
        fill_dir = 0
        if fill.direction == 'BUY':
            fill_dir = 1
        if fill.direction == 'SELL':
            fill_dir = -1

        self.current_postitions[fill.symbol] += fill_dir*fill.quantity

    def update_holdings_from_fill(self, fill):
        """
        从FillEvent对象中读取数据以更新头寸市值 (holdings value)
        参数：
        fill: FillEvent对象
        """
        fill_dir = 0
        if fill.direction == 'BUY':
            fill_dir = 1
        if fill.direction == 'SELL':
            fill_dir = -1

        fill_cost = self.bars.get_latest_bars(fill.symbol)[0][5] # close price
        cost = fill_dir * fill_cost * fill.quantity

        commission = 3.0/10000 * cost # 手续费简单按照万3来算的
                                      # 手续费需要优化，最好在Fill时间中实现

        self.current_holdings[fill.symbol] += cost
        self.current_holdings['commission'] += commission 
        self.current_holdings['cash'] -= (cost + commission)
        self.current_holdings['total'] -= (cost + commission)

    def update_fill(self, event):
        """
        从FillEvent中更新组合的头寸和市值，实现
        """
        if event.e_type == 'FILL':
            self.update_position_from_fill(event)
            self.update_holdings_from_fill(event)

    # (2) 与SignalEvent对象交互: 通过一个工具函数来实现Portofio抽象基类的update_signal()

    def generate_naive_order(self, signal):
        """
        简单地将signal对象乘以固定的数量作为OrderEvent对象，
        此函数不采取任何风险管理和仓位控制
        """
        order = None

        symbol = signal.symbol
        direction = signal.signal_type
        # strength = signal.strength 尚未定义此属性
        # mkt_quantity = floor(100 * strength)
        mkt_quantity = 100
        cur_quantity = self.current_postitions[symbol]
        order_type = 'MKT'

        if direction == 'LONG' and cur_quantity == 0: 
            order = OrderEvent(symbol, order_type, mkt_quantity, 'BUY')
        if direction == 'SHORT' and cur_quantity == 0:
            order = OrderEvent(symbol, order_type, mkt_quantity, 'SELL')

        if direction == 'EXIT' and cur_quantity > 0:
            order = OrderEvent(symbol, order_type, abs(cur_quantity), 'SELL')
        if direction == 'EXIT' and cur_quantity < 0:
            order = OrderEvent(symbol, order_type, abs(cur_quantity), 'BUY')

        return order

    def update_signal(self, event):
        """
        基于组合管理的逻辑，通过SignalEvent对象来产生新的orders
        """
        if event.e_type == 'SIGNAL':
            order_event = self.generate_naive_order(event)
            self.events.put(order_event)


    ### 股票曲线的功能函数，用于perfomance的计算
    # TODO：
    #     设置perfomance的modulue，强化可视化的功能
    def create_equity_curve_dataframe(self):
        """
        从all_holdings的字典列表中生成pandas的DataFrame
        展示profit and loss (PnL)
        """
        curve = pd.DataFrame(self.all_holdings)
        curve.set_index('datetime', inplace=True) # 就地修改，不生成新对象
        curve['returns'] = curve['total'].pct_change() # 计算百分比变化
        curve['equity_curve'] = (1.0 + curve['returns']).cumprod() # 计算累计值
        self.equity_curve = curve
