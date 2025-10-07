"""
Configuration Validation System - Pacifica Bot
Validates configurations without altering main functionality

IMPORTANT: This module only VALIDATES and WARNS about configurations.
Does not alter bot behavior, only informs about possible problems.
"""

import os
import logging
from typing import List, Tuple, Dict, Any

def validate_strategy_config(strategy_type: str) -> Tuple[List[str], List[str]]:
    """
    Validates strategy-specific configurations
    
    Args:
        strategy_type: Tipo da estratégia ('grid', 'multi_asset', etc.)
        
    Returns:
        Tuple[errors, warnings]: Lista de erros críticos e avisos
    """
    errors = []
    warnings = []
    
    if strategy_type in ['multi_asset', 'multi_asset_enhanced']:
        # Validar TP/SL para multi-asset
        try:
            tp_percent = float(os.getenv('TAKE_PROFIT_PERCENT', '2.0'))  # ✅ Meta de lucro maior
            sl_percent = float(os.getenv('STOP_LOSS_PERCENT', '1.5'))   # ✅ Limite de perda menor
            
            # Validações de range
            if tp_percent <= 0 or tp_percent > 10:
                errors.append("TAKE_PROFIT_PERCENT must be between 0.1 and 10")
            if sl_percent <= 0 or sl_percent > 20:
                errors.append("STOP_LOSS_PERCENT must be between 0.1 and 20")
                
            # Validação lógica: TP deve ser maior que SL (queremos ganhar mais do que arriscamos perder)
            if tp_percent <= sl_percent:
                errors.append("TAKE_PROFIT_PERCENT must be greater than STOP_LOSS_PERCENT")
                errors.append(f"Current configuration: TP={tp_percent}% <= SL={sl_percent}% (no economic sense)")
                
            # Avisos de configuração
            if tp_percent > 5:
                warnings.append(f"TAKE_PROFIT_PERCENT={tp_percent}% is too high - consider lower values")
            if sl_percent > 10:
                warnings.append(f"STOP_LOSS_PERCENT={sl_percent}% is too high - high risk")
                
        except (ValueError, TypeError):
            errors.append("TAKE_PROFIT_PERCENT and STOP_LOSS_PERCENT must be valid numbers")
            
        # Validar outras configurações multi-asset
        try:
            max_trades = int(os.getenv('MAX_CONCURRENT_TRADES', '3'))
            if max_trades < 1 or max_trades > 20:
                errors.append("MAX_CONCURRENT_TRADES must be between 1 and 20")
            elif max_trades > 10:
                warnings.append(f"MAX_CONCURRENT_TRADES={max_trades} is high - consider starting with 3-5")
        except (ValueError, TypeError):
            errors.append("MAX_CONCURRENT_TRADES must be an integer")
            
    elif strategy_type in ['pure_grid', 'market_making', 'dynamic_grid', 'grid']:
        # Avisar se TP/SL configurado para grid (será ignorado)
        if os.getenv('TAKE_PROFIT_PERCENT') or os.getenv('STOP_LOSS_PERCENT'):
            warnings.append("TP/SL configured but will be IGNORED for Grid strategies")
            warnings.append("Grid strategies use only limit orders in the grid system")
            
        # Validar configurações específicas do grid
        try:
            grid_levels = int(os.getenv('GRID_LEVELS', '8'))
            if grid_levels < 2 or grid_levels > 100:
                errors.append("GRID_LEVELS must be between 2 and 100")
            elif grid_levels > 50:
                warnings.append(f"GRID_LEVELS={grid_levels} is too high - many simultaneous orders")
        except (ValueError, TypeError):
            errors.append("GRID_LEVELS must be an integer")
    
    return errors, warnings

def validate_trading_params() -> Tuple[List[str], List[str]]:
    """
    Validates general trading parameters
    
    Returns:
        Tuple[errors, warnings]: Lista de erros críticos e avisos
    """
    errors = []
    warnings = []
    
    try:
        # Validação de alavancagem
        leverage = int(os.getenv('LEVERAGE', '10'))
        if leverage < 1 or leverage > 50:
            errors.append("LEVERAGE must be between 1 and 50")
        elif leverage > 20:
            warnings.append(f"LEVERAGE={leverage} is high - high risk, consider 5-15")
        elif leverage == 1:
            warnings.append("LEVERAGE=1 means no leverage - profits will be smaller")
            
    except (ValueError, TypeError):
        errors.append("LEVERAGE must be an integer")
    
    try:
        # Validação de tamanho de posição
        order_size = float(os.getenv('ORDER_SIZE_USD', '35'))
        if order_size < 1 or order_size > 1000:
            errors.append("ORDER_SIZE_USD must be between 1 and 1000")
        elif order_size > 500:
            warnings.append(f"ORDER_SIZE_USD={order_size} is high - recommended to start with 20-50")
        elif order_size < 10:
            warnings.append(f"ORDER_SIZE_USD={order_size} is low - profits may be minimal")
            
    except (ValueError, TypeError):
        errors.append("ORDER_SIZE_USD must be a valid number")
        
    try:
        # Validação de espaçamento do grid
        spacing = float(os.getenv('GRID_SPACING_PERCENT', '0.2'))
        if spacing < 0.01 or spacing > 5:
            errors.append("GRID_SPACING_PERCENT must be between 0.01 and 5")
        elif spacing < 0.1:
            warnings.append(f"GRID_SPACING_PERCENT={spacing}% too low - many close orders")
        elif spacing > 2:
            warnings.append(f"GRID_SPACING_PERCENT={spacing}% high - grid may be less efficient")
            
    except (ValueError, TypeError):
        errors.append("GRID_SPACING_PERCENT must be a valid number")
        
    try:
        # Validação de intervalo de rebalanceamento
        rebalance_interval = int(os.getenv('REBALANCE_INTERVAL_SECONDS', '60'))
        if rebalance_interval < 10 or rebalance_interval > 3600:
            errors.append("REBALANCE_INTERVAL_SECONDS must be between 10 and 3600")
        elif rebalance_interval < 30:
            warnings.append(f"REBALANCE_INTERVAL_SECONDS={rebalance_interval}s too low - may overload API")
            
    except (ValueError, TypeError):
        errors.append("REBALANCE_INTERVAL_SECONDS must be an integer")
    
    return errors, warnings

def validate_api_credentials() -> Tuple[List[str], List[str]]:
    """
    Validates required API credentials
    
    Returns:
        Tuple[errors, warnings]: Lista de erros críticos e avisos
    """
    errors = []
    warnings = []
    
    # Validar chaves principais
    main_key = os.getenv('MAIN_PUBLIC_KEY', '').strip()
    agent_key = os.getenv('AGENT_PRIVATE_KEY_B58', '').strip()
    
    if not main_key:
        errors.append("MAIN_PUBLIC_KEY not configured - bot cannot operate")
    elif len(main_key) < 32:
        errors.append("MAIN_PUBLIC_KEY too short - must be at least 32 characters")
        
    if not agent_key:
        errors.append("AGENT_PRIVATE_KEY_B58 not configured - bot cannot operate")
    elif len(agent_key) < 32:
        errors.append("AGENT_PRIVATE_KEY_B58 too short - must be at least 32 characters")
        
    # Validar endpoints
    api_address = os.getenv('API_ADDRESS', '')
    if not api_address:
        errors.append("API_ADDRESS not configured")
    elif not api_address.startswith('https://'):
        warnings.append("API_ADDRESS does not use HTTPS - connection may be insecure")
        
    ws_base_url = os.getenv('WS_BASE_URL', '')
    if not ws_base_url:
        warnings.append("WS_BASE_URL not configured - WebSocket features unavailable")
    elif not ws_base_url.startswith('wss://'):
        warnings.append("WS_BASE_URL does not use WSS - connection may be insecure")
        
    return errors, warnings

def validate_symbol_config(strategy_type: str) -> Tuple[List[str], List[str]]:
    """
    Validates symbol configurations based on strategy
    
    Args:
        strategy_type: Tipo da estratégia
        
    Returns:
        Tuple[errors, warnings]: Lista de erros críticos e avisos
    """
    errors = []
    warnings = []
    
    if strategy_type in ['pure_grid', 'market_making', 'dynamic_grid', 'grid']:
        # Grid strategies usam um símbolo único
        symbol = os.getenv('SYMBOL', 'BTC').upper()
        if not symbol:
            errors.append("SYMBOL not configured for Grid strategy")
        elif len(symbol) < 2:
            errors.append("SYMBOL must be at least 2 characters")
            
    elif strategy_type in ['multi_asset', 'multi_asset_enhanced']:
        # Multi-asset strategies usam múltiplos símbolos
        symbols_config = os.getenv('SYMBOLS', 'AUTO')
        if symbols_config == 'AUTO':
            warnings.append("SYMBOLS=AUTO - bot will detect symbols automatically")
        elif not symbols_config:
            errors.append("SYMBOLS not configured for Multi-Asset strategy")
        else:
            # Validar lista de símbolos
            symbols = [s.strip().upper() for s in symbols_config.split(',') if s.strip()]
            if len(symbols) == 0:
                errors.append("SYMBOLS list is empty")
            elif len(symbols) > 50:
                warnings.append(f"SYMBOLS={len(symbols)} symbols - consider reducing to 10-20")
                
    return errors, warnings

def run_all_validations(strategy_type: str) -> Dict[str, Any]:
    """
    Executes all validations and returns consolidated report
    
    Args:
        strategy_type: Tipo da estratégia a ser validada
        
    Returns:
        Dict com resultados das validações
    """
    all_errors = []
    all_warnings = []
    
    # Executar todas as validações
    validation_functions = [
        lambda: validate_strategy_config(strategy_type),
        validate_trading_params,
        validate_api_credentials,
        lambda: validate_symbol_config(strategy_type)
    ]
    
    for validation_func in validation_functions:
        try:
            errors, warnings = validation_func()
            all_errors.extend(errors)
            all_warnings.extend(warnings)
        except Exception as e:
            all_warnings.append(f"Erro durante validação: {str(e)}")
    
    # Gerar relatório
    return {
        'strategy_type': strategy_type,
        'errors': all_errors,
        'warnings': all_warnings,
        'has_critical_errors': len(all_errors) > 0,
        'total_issues': len(all_errors) + len(all_warnings),
        'validation_passed': len(all_errors) == 0
    }

def print_validation_report(validation_result: Dict[str, Any], logger=None) -> None:
    """
    Prints formatted validation report
    
    Args:
        validation_result: Resultado das validações
        logger: Logger para output (opcional, usa print se None)
    """
    def log_message(level: str, message: str):
        if logger:
            getattr(logger, level.lower())(message)
        else:
            print(f"[{level.upper()}] {message}")
    
    strategy = validation_result['strategy_type']
    errors = validation_result['errors']
    warnings = validation_result['warnings']
    
    log_message('info', "=" * 60)
    log_message('info', f"🔧 VALIDATION REPORT - {strategy.upper()}")
    log_message('info', "=" * 60)
    
    if validation_result['validation_passed']:
        log_message('info', "✅ ALL validations passed!")
    else:
        log_message('error', f"❌ {len(errors)} CRITICAL ERROR(S) found")
        
    if warnings:
        log_message('warning', f"⚠️ {len(warnings)} WARNING(S) found")
        
    # Mostrar erros críticos
    if errors:
        log_message('error', "\n🚨 CRITICAL ISSUES:")
        for i, error in enumerate(errors, 1):
            log_message('error', f"  {i}. {error}")
            
    # Mostrar avisos
    if warnings:
        log_message('warning', "\n⚠️ WARNINGS:")
        for i, warning in enumerate(warnings, 1):
            log_message('warning', f"  {i}. {warning}")
            
    log_message('info', "=" * 60)
    
    if errors:
        log_message('error', "❌ Bot may not function correctly with these configurations")
    else:
        log_message('info', "✅ Configurations validated - bot ready to execute")

# Funções utilitárias para integração
def validate_config_and_warn(strategy_type: str, logger=None) -> bool:
    """
    Executes validations and displays report - convenience function
    
    Args:
        strategy_type: Tipo da estratégia
        logger: Logger para output
        
    Returns:
        True se não há erros críticos, False caso contrário
    """
    try:
        result = run_all_validations(strategy_type)
        print_validation_report(result, logger)
        return result['validation_passed']
    except Exception as e:
        if logger:
            logger.error(f"Erro durante validação: {e}")
        else:
            print(f"[ERROR] Erro durante validação: {e}")
        return True  # Não bloquear execução por erro de validação

if __name__ == "__main__":
    # Teste das validações
    import sys
    strategy = sys.argv[1] if len(sys.argv) > 1 else 'market_making'
    
    print("🔧 Testing Validation System")
    print(f"Estratégia: {strategy}")
    print("-" * 40)
    
    result = run_all_validations(strategy)
    print_validation_report(result)