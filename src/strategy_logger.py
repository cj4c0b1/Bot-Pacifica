"""
Strategy Logger - Strategy-Specific Logging System
Filters and customizes logs based on active strategy type
"""

import logging
import os
from typing import Dict, Any, Optional


class StrategyLogger:
    """Logger that adapts messages based on active strategy"""
    
    def __init__(self, base_logger: logging.Logger, strategy_type: str):
        self.base_logger = base_logger
        self.strategy_type = strategy_type.lower()
        
        # Definir filtros de mensagens por estratégia
        self.setup_filters()
    
    def setup_filters(self):
        """Sets up strategy-specific filters"""
        
        # Words/phrases that should be filtered for multi_asset and multi_asset_enhanced
        self.multi_asset_filters = [
            'grid', 'Grid', 'GRID',
            'níveis', 'níveis', 'levels',
            'spacing', 'espaçamento',
            'range', 'Range', 'RANGE',
            'rebalanceamento', 'rebalancing'
        ]
        
        # Substituições específicas para multi_asset
        self.multi_asset_replacements = {
            'Grid': 'Multi-Asset',
            'grid': 'estratégia',
            'níveis': 'posições',
            'levels': 'positions',
            'rebalanceamento': 'análise de mercado',
            'rebalancing': 'market analysis'
        }
        
        # Specific replacements for multi_asset_enhanced
        self.enhanced_replacements = {
            'Grid': 'Enhanced Multi-Asset',
            'grid': 'algoritmo inteligente',
            'níveis': 'sinais detectados',
            'levels': 'detected signals',
            'rebalanceamento': 'análise técnica avançada',
            'rebalancing': 'advanced technical analysis'
        }
        
        # Words that should be filtered for grid strategies
        self.grid_filters = [
            'multi-asset', 'Multi-Asset', 'MULTI-ASSET',
            'scalping', 'Scalping', 'SCALPING'
        ]
        
    def _should_filter_message(self, message: str) -> bool:
        """Determines if a message should be filtered"""
        
        # Critical messages always pass
        critical_keywords = ['erro', 'error', 'falhou', 'failed', 'crítico', 'critical']
        if any(word in message.lower() for word in critical_keywords):
            return True
            
        # Initialization messages always pass
        init_keywords = ['inicializando', 'initializing', 'carregados', 'loaded', 'pronto', 'ready']
        if any(word in message.lower() for word in init_keywords):
            return True
        
        if self.strategy_type in ['multi_asset', 'multi_asset_enhanced']:
            # Para multi_asset e enhanced, filtrar mensagens relacionadas ao grid tradicional
            for filter_word in self.multi_asset_filters:
                if filter_word.lower() in message.lower():
                    return False  # Filtrar (não mostrar)
                    
        elif self.strategy_type in ['pure_grid', 'market_making']:
            # Para grid strategies, filtrar mensagens de multi-asset
            for filter_word in self.grid_filters:
                if filter_word.lower() in message.lower():
                    return False  # Filtrar (não mostrar)
                    
        return True  # Não filtrar
        
    def _adapt_message(self, message: str) -> str:
        """Adapts message for active strategy"""
        
        adapted_message = message
        
        if self.strategy_type == 'multi_asset':
            # Substituir termos específicos do grid para multi_asset básico
            for old_term, new_term in self.multi_asset_replacements.items():
                adapted_message = adapted_message.replace(old_term, new_term)
        elif self.strategy_type == 'multi_asset_enhanced':
            # Substituir termos específicos para enhanced strategy
            for old_term, new_term in self.enhanced_replacements.items():
                adapted_message = adapted_message.replace(old_term, new_term)
                
        return adapted_message
    
    def _get_strategy_prefix(self) -> str:
        """Gets strategy-specific prefix"""
        
        prefixes = {
            'multi_asset': '🌐',
            'multi_asset_enhanced': '🧠',
            'pure_grid': '📊',
            'market_making': '🎯'
        }
        
        return prefixes.get(self.strategy_type, '🤖')
    
    def info(self, message: str, force: bool = False):
        """Log INFO with strategy filtering"""
        
        if not force and not self._should_filter_message(message):
            return
            
        adapted_message = self._adapt_message(message)
        self.base_logger.info(adapted_message)
    
    def debug(self, message: str, force: bool = False):
        """Log DEBUG with strategy filtering"""
        
        if not force and not self._should_filter_message(message):
            return
            
        adapted_message = self._adapt_message(message)
        self.base_logger.debug(adapted_message)
    
    def warning(self, message: str, force: bool = False):
        """Log WARNING - always show important warnings"""
        
        adapted_message = self._adapt_message(message)
        self.base_logger.warning(adapted_message)
    
    def error(self, message: str, force: bool = False):
        """Log ERROR - always show errors"""
        
        adapted_message = self._adapt_message(message)
        self.base_logger.error(adapted_message)
    
    # Enhanced Strategy specific methods
    def enhanced_signal(self, symbol: str, score: int, confidence: float, action: str):
        """Log específico para sinais Enhanced"""
        if self.strategy_type == 'multi_asset_enhanced':
            message = f"🧠 {symbol} - Score: {score}/100, Conf: {confidence:.1%} → {action.upper()}"
            self.base_logger.info(message)
    
    def enhanced_analysis(self, symbol: str, indicators: dict):
        """Log análise detalhada dos indicadores"""
        if self.strategy_type == 'multi_asset_enhanced':
            details = []
            for indicator, value in indicators.items():
                details.append(f"{indicator}: {value}")
            message = f"🔍 {symbol} - {', '.join(details)}"
            self.base_logger.debug(message)
    
    def strategy_info(self, message: str):
        """Strategy-specific info with correct emoji"""
        prefix = self._get_strategy_prefix()
        adapted_message = self._adapt_message(f"{prefix} {message}")
        self.base_logger.info(adapted_message)
    
    def strategy_info(self, message: str):
        """Strategy-specific log with prefix"""
        
        prefix = self._get_strategy_prefix()
        adapted_message = f"{prefix} {self._adapt_message(message)}"
        self.base_logger.info(adapted_message)
    
    # Passthrough methods for compatibility
    def __getattr__(self, name):
        """Repassar outros métodos para o logger base"""
        return getattr(self.base_logger, name)


def create_strategy_logger(name: str, strategy_type: str) -> StrategyLogger:
    """Factory function to create strategy-specific logger"""
    
    base_logger = logging.getLogger(name)
    return StrategyLogger(base_logger, strategy_type)


def get_strategy_specific_messages(strategy_type: str) -> Dict[str, str]:
    """Gets strategy-specific messages"""
    
    messages = {
        'multi_asset': {
            'initialization': '🌐 Inicializando estratégia Multi-Asset Scalping...',
            'ready': '✅ Estratégia Multi-Asset pronta para trading',
            'monitoring': '👀 Monitorando oportunidades em múltiplos ativos',
            'position_opened': '📈 Nova posição aberta',
            'position_closed': '💰 Posição fechada com',
            'no_opportunities': '⏳ Aguardando oportunidades de mercado...'
        },
        'multi_asset_enhanced': {
            'initialization': '🧠 Inicializando Enhanced Multi-Asset Strategy...',
            'ready': '✅ Algoritmo inteligente com 5 indicadores ativo',
            'monitoring': '🔍 Analisando mercado com algoritmo avançado',
            'signal_detected': '⚡ Sinal detectado - Score:',
            'position_opened': '🚀 Posição Enhanced aberta',
            'position_closed': '💎 Posição Enhanced fechada com',
            'no_opportunities': '🤔 Aguardando sinais de alta qualidade...',
            'analyzing': '📊 Analisando 5 indicadores técnicos...'
        },
        'pure_grid': {
            'initialization': '📊 Inicializando estratégia Pure Grid...',
            'ready': '✅ Grid fixo configurado e operacional',
            'monitoring': '🔍 Monitorando execuções no grid fixo',
            'grid_executed': '🎯 Ordem do grid executada',
            'grid_rebalanced': '⚖️ Grid rebalanceado',
            'out_of_range': '⚠️ Preço saiu do range configurado'
        },
        'market_making': {
            'initialization': '🎯 Inicializando estratégia Market Making...',
            'ready': '✅ Grid dinâmico ativo e adaptativo',
            'monitoring': '📈 Monitorando mercado para ajustes dinâmicos',
            'grid_shifted': '🔄 Grid reposicionado por movimento de mercado',
            'spread_adjusted': '📏 Spread ajustado por volatilidade'
        }
    }
    
    return messages.get(strategy_type.lower(), messages['multi_asset'])