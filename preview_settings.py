"""Resolution percentages shared by the panel and Sony preview exporter."""

PRESETS = {100: '100% · полное', 75: '75% · детальнее', 50: '50% · быстро'}
CUSTOM = 'Свой процент…'


def validate_percent(value):
    if isinstance(value, bool):
        raise ValueError('Укажите целый процент от 1 до 100.')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('Укажите целый процент от 1 до 100.') from None
    if not 1 <= number <= 100 or not number.is_integer():
        raise ValueError('Укажите целый процент от 1 до 100.')
    return int(number)


def scaled_size(width, height, percent):
    percent = validate_percent(percent)
    if width <= 0 or height <= 0:
        raise ValueError('Invalid source dimensions.')
    return max(1, round(width * percent / 100)), max(1, round(height * percent / 100))


def preferences(values):
    if not isinstance(values, dict):
        values = {}
    legacy = {'Полное разрешение': 100, 'Детальнее · 3000 px': 75}
    try:
        percent = validate_percent(values.get('preview_percent', legacy.get(values.get('preview_size'), 50)))
    except ValueError:
        percent = 50
    try:
        custom = validate_percent(values.get('custom_percent', 35))
    except ValueError:
        custom = 35
    mode = 'custom' if values.get('preview_mode') == 'custom' or percent not in PRESETS else 'preset'
    if mode == 'custom':
        custom = percent
    return percent, custom, mode


def custom_label(percent):
    return 'Свой: %d%%' % validate_percent(percent)
