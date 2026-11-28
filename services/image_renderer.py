"""
services/image_renderer.py
Модуль динамічної візуалізації розкладів Таро, сумісності та особистих Арканів на базі Pillow.
Генерує естетичні темні графічні картки із золотим оздобленням без збереження на диск (в пам'яті через BytesIO).
"""

import io
import math
import random
import logging
from typing import List, Dict, Any, Union, Optional
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("services.image_renderer")

# Палітра кольорів
BG_COLOR = (26, 26, 26)           # Глибокий графітово-чорний #1A1A1A
CARD_BG = (32, 30, 28)            # Темний фон картки
GOLD_PRIMARY = (213, 178, 112)    # #D5B270
GOLD_SECONDARY = (197, 168, 128)  # #C5A880
GOLD_LIGHT = (244, 222, 178)      # #F4DEB2
GOLD_MUTED = (110, 92, 66)        # Приглушене золото для тонких ліній
TEXT_OFFWHITE = (234, 230, 225)   # #EAE6E1
TEXT_MUTED = (175, 170, 165)      # Світло-сірий для підписів
REVERSED_ACCENT = (215, 140, 120) # М'який акцент для перевернутих карт

CANDIDATE_FONTS = [
    # Шрифти з папки проєкту
    "assets/fonts/PlayfairDisplay-Bold.ttf",
    "assets/fonts/Montserrat.ttf",
    "assets/fonts/Geometria-Medium.ttf",
    "assets/fonts/Cinzel-Bold.ttf",
    # Системні шрифти Linux / Render
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    # Системні шрифти macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    # Системні шрифти Windows
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _get_font(size: int, bold: bool = False, serif: bool = False) -> ImageFont.ImageFont:
    """Завантажує найкращий доступний шрифт із списку або повертає дефолтний."""
    # Пріоритет за типом
    target_names = []
    if serif:
        target_names = ["Playfair", "Cinzel", "Times", "DejaVuSerif"]
    elif bold:
        target_names = ["PlayfairDisplay-Bold", "Montserrat", "Bold", "arialbd"]
    else:
        target_names = ["Montserrat", "Arial", "DejaVuSans", "Liberation"]

    # Спочатку шукаємо за назвою
    for candidate in CANDIDATE_FONTS:
        if any(t.lower() in candidate.lower() for t in target_names):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue

    # Загальний перебір усіх шляхів
    for candidate in CANDIDATE_FONTS:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue

    return ImageFont.load_default()


def to_roman(n: int) -> str:
    """Конвертує число в римську цифру."""
    if n == 0:
        return "0"
    val = [100, 90, 50, 40, 10, 9, 5, 4, 1]
    syb = ["C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
    roman = ""
    i = 0
    while n > 0:
        for _ in range(n // val[i]):
            roman += syb[i]
            n -= val[i]
        i += 1
    return roman


def _draw_star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r_out: float, r_in: float, fill: tuple):
    """Малює 4-кінцеву або 8-кінцеву зірочку."""
    points = []
    for i in range(8):
        angle = i * math.pi / 4 - math.pi / 2
        r = r_out if i % 2 == 0 else r_in
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(points, fill=fill)


def _draw_diamond(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, outline: tuple, fill: Optional[tuple] = None, width: int = 1):
    """Малює ромб."""
    pts = [(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)]
    draw.polygon(pts, fill=fill, outline=outline, width=width)


def _draw_background_stars(draw: ImageDraw.ImageDraw, width: int, height: int, count: int = 40, seed: int = 42):
    """Малює розсип дрібних золотих точок та 4-кінцевих зірок на фоні."""
    rng = random.Random(seed)
    for _ in range(count):
        x = rng.randint(25, width - 25)
        y = rng.randint(25, height - 25)
        r_type = rng.random()
        if r_type < 0.2:
            # 4-кінцева маленька зірочка
            _draw_star(draw, x, y, r_out=4.0, r_in=1.2, fill=GOLD_PRIMARY)
        elif r_type < 0.5:
            # Точка кольору золота
            draw.rectangle([x, y, x + 1.5, y + 1.5], fill=GOLD_LIGHT)
        else:
            # Дрібна приглушена точка
            draw.point((x, y), fill=GOLD_MUTED)


def _draw_card_box(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    card_bg: tuple = CARD_BG,
    border_color: tuple = GOLD_PRIMARY,
    inner_padding: int = 6
):
    """Отрисовує картку з подвійною золотою рамкою та кутовими візерунками."""
    # Тіло картки
    draw.rectangle([x0, y0, x1, y1], fill=card_bg, outline=border_color, width=2)
    # Внутрішня тонка рамка
    ix0, iy0, ix1, iy1 = x0 + inner_padding, y0 + inner_padding, x1 - inner_padding, y1 - inner_padding
    draw.rectangle([ix0, iy0, ix1, iy1], outline=GOLD_MUTED, width=1)

    # Кутові акценти (маленькі діагональні кутики)
    cs = 10
    draw.line([(ix0, iy0 + cs), (ix0, iy0), (ix0 + cs, iy0)], fill=border_color, width=1)
    draw.line([(ix1 - cs, iy0), (ix1, iy0), (ix1, iy0 + cs)], fill=border_color, width=1)
    draw.line([(ix0, iy1 - cs), (ix0, iy1), (ix0 + cs, iy1)], fill=border_color, width=1)
    draw.line([(ix1 - cs, iy1), (ix1, iy1), (ix1, iy1 - cs)], fill=border_color, width=1)


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: float,
    cy: float,
    font: ImageFont.ImageFont,
    fill: tuple,
    anchor: str = "mm"
):
    """Малює відцентрований текст."""
    draw.text((cx, cy), text, font=font, fill=fill, anchor=anchor)


def _draw_sacred_emblem(draw: ImageDraw.ImageDraw, cx: float, cy: float, radius: float = 40.0, is_reversed: bool = False):
    """Отрисовує геометричний золотий сакральний символ у центрі карти."""
    # Концентричні кола
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=GOLD_MUTED, width=1)
    draw.ellipse([cx - radius * 0.7, cy - radius * 0.7, cx + radius * 0.7, cy + radius * 0.7], outline=GOLD_PRIMARY, width=1)

    # Центральна 8-кінцева зірка
    _draw_star(draw, cx, cy, r_out=radius * 0.55, r_in=radius * 0.2, fill=GOLD_PRIMARY)

    # Ромб з тонких ліній
    _draw_diamond(draw, cx, cy, w=radius * 1.5, h=radius * 1.5, outline=GOLD_SECONDARY, width=1)

    # Індикатор орієнтації
    if is_reversed:
        # Стрілка або трикутник донизу
        draw.polygon([(cx - 7, cy + radius + 10), (cx + 7, cy + radius + 10), (cx, cy + radius + 18)], fill=REVERSED_ACCENT)
    else:
        # Маленька точка/іскра вгорі
        draw.polygon([(cx - 4, cy - radius - 8), (cx + 4, cy - radius - 8), (cx, cy - radius - 14)], fill=GOLD_LIGHT)


# ---------------------------------------------------------------------------
# 1. ТРИКАРТКОВИЙ РОЗКЛАД ТАРО (1200x675)
# ---------------------------------------------------------------------------

def render_tarot_spread(cards_metadata: List[Union[Dict[str, Any], Any]]) -> bytes:
    """
    Генерує 16:9 горизонтальний розклад із 3 карт (1200x675 px).
    Розрахунок координат карт гарантує ідеальну симетрію та відсутність наїздів на полотні.
    """
    canvas_w = 1200
    canvas_h = 675
    img = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 1. Зовнішня рамка полотна та зоряне небо
    draw.rectangle([14, 14, canvas_w - 14, canvas_h - 14], outline=GOLD_MUTED, width=1)
    draw.rectangle([18, 18, canvas_w - 18, canvas_h - 18], outline=GOLD_PRIMARY, width=1)
    _draw_background_stars(draw, canvas_w, canvas_h, count=45, seed=108)

    # 2. Заголовок зверху
    font_title = _get_font(26, bold=True, serif=True)
    _draw_centered_text(draw, "✦  Т В І Й   Т Р И К А Р Т К О В И Й   Р О З К Л А Д  ✦", canvas_w / 2, 58, font_title, GOLD_PRIMARY)

    # 3. Підпис знизу
    font_footer = _get_font(15, bold=False, serif=False)
    _draw_centered_text(draw, "VELARA tarot & psychology  ✦  @Velara_bot", canvas_w / 2, canvas_h - 35, font_footer, GOLD_SECONDARY)

    # 4. Розрахунок позицій 3 карт:
    # 3 карти по 260px = 780px. Залишок 420px ділиться на 4 рівні проміжки по 105px!
    card_w = 260
    card_h = 420
    num_cards = 3
    gap = (canvas_w - (num_cards * card_w)) / (num_cards + 1)  # 105.0 px
    card_y0 = (canvas_h - card_h) // 2                        # 127 px
    card_y1 = card_y0 + card_h                                # 547 px

    roles = [
        "1. Основа ситуації",
        "2. Приховане",
        "3. Порада / Вектор"
    ]

    for i in range(min(num_cards, len(cards_metadata))):
        c = cards_metadata[i]
        # Читаємо атрибути об'єкта чи словника
        if isinstance(c, dict):
            c_name = c.get("name_ua") or c.get("name") or "Карта"
            c_is_rev = bool(c.get("is_reversed", False))
            c_id = c.get("id", "")
        else:
            c_name = getattr(c, "name_ua", getattr(c, "name", "Карта"))
            c_is_rev = bool(getattr(c, "is_reversed", False))
            c_id = getattr(c, "id", "")

        x0 = int(gap + i * (card_w + gap))
        x1 = x0 + card_w
        cx = (x0 + x1) / 2

        # Отрисовка рамки картки
        _draw_card_box(draw, x0, card_y0, x1, card_y1, card_bg=CARD_BG, border_color=GOLD_PRIMARY, inner_padding=7)

        # Визначаємо номер або римську цифру
        num_str = ""
        if "major_" in str(c_id):
            try:
                major_num = int(str(c_id).split("_")[1])
                num_str = to_roman(major_num)
            except Exception:
                num_str = "✦"
        else:
            num_str = "✦"

        # Римська цифра
        font_roman = _get_font(20, bold=True, serif=True)
        _draw_centered_text(draw, num_str, cx, card_y0 + 35, font_roman, GOLD_PRIMARY)

        # Назва карти
        font_card_name = _get_font(17 if len(c_name) < 18 else 14, bold=True, serif=False)
        _draw_centered_text(draw, c_name.upper(), cx, card_y0 + 68, font_card_name, TEXT_OFFWHITE)

        # Розділювач
        draw.line([(cx - 50, card_y0 + 88), (cx + 50, card_y0 + 88)], fill=GOLD_MUTED, width=1)

        # Центральний сакральний символ
        _draw_sacred_emblem(draw, cx, card_y0 + 195, radius=42.0, is_reversed=c_is_rev)

        # Положення (Пряма або Перевернута)
        state_text = "ПЕРЕВЕРНУТА" if c_is_rev else "ПРЯМА"
        state_color = REVERSED_ACCENT if c_is_rev else GOLD_SECONDARY
        font_state = _get_font(13, bold=True, serif=False)
        _draw_centered_text(draw, state_text, cx, card_y0 + 315, font_state, state_color)

        # Лінія перед роллю
        draw.line([(x0 + 20, card_y1 - 65), (x1 - 20, card_y1 - 65)], fill=GOLD_MUTED, width=1)

        # Роль карти в розкладі
        role_text = roles[i] if i < len(roles) else f"{i+1}. Позиція"
        font_role = _get_font(14, bold=False, serif=False)
        _draw_centered_text(draw, role_text, cx, card_y1 - 35, font_role, GOLD_LIGHT)

    bio = io.BytesIO()
    img.save(bio, format="JPEG", quality=92, optimize=True)
    return bio.getvalue()


# ---------------------------------------------------------------------------
# 2. КАРТКА СУМІСНОСТІ ПАРИ (1200x675)
# ---------------------------------------------------------------------------

def render_compatibility(
    name1: str,
    name2: str,
    date1: str,
    date2: str,
    result_num: int,
    result_name: str,
    **kwargs
) -> bytes:
    """
    Генерує 16:9 горизонтальну карточку сумісності (1200x675 px).
    Містить дві бокові рамки партнерів та центральну карту Аркана союзу.
    """
    canvas_w = 1200
    canvas_h = 675
    img = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 1. Рамка полотна та зорі
    draw.rectangle([14, 14, canvas_w - 14, canvas_h - 14], outline=GOLD_MUTED, width=1)
    draw.rectangle([18, 18, canvas_w - 18, canvas_h - 18], outline=GOLD_PRIMARY, width=1)
    _draw_background_stars(draw, canvas_w, canvas_h, count=40, seed=777)

    # 2. Заголовок
    font_title = _get_font(26, bold=True, serif=True)
    _draw_centered_text(draw, "✦  С У М І С Н І С Т Ь   П А Р И  ✦", canvas_w / 2, 58, font_title, GOLD_PRIMARY)

    # 3. Підпис знизу
    font_footer = _get_font(15, bold=False, serif=False)
    _draw_centered_text(draw, "VELARA tarot & psychology  ✦  @Velara_bot", canvas_w / 2, canvas_h - 35, font_footer, GOLD_SECONDARY)

    # 4. Ліва картка (Партнер 1)
    p_w, p_h = 280, 360
    p_y0 = 150
    p_y1 = p_y0 + p_h

    # Партнер 1 (x0 = 80, x1 = 360)
    p1_x0, p1_x1 = 80, 80 + p_w
    p1_cx = (p1_x0 + p1_x1) / 2
    _draw_card_box(draw, p1_x0, p_y0, p1_x1, p_y1, card_bg=CARD_BG, border_color=GOLD_SECONDARY, inner_padding=6)

    font_partner_tag = _get_font(13, bold=True, serif=False)
    _draw_centered_text(draw, "✦ ПАРТНЕР 1 ✦", p1_cx, p_y0 + 35, font_partner_tag, GOLD_PRIMARY)

    font_p_name = _get_font(22 if len(name1) < 14 else 17, bold=True, serif=False)
    _draw_centered_text(draw, name1.upper(), p1_cx, p_y0 + 85, font_p_name, TEXT_OFFWHITE)

    font_p_date = _get_font(16, bold=False, serif=False)
    _draw_centered_text(draw, date1, p1_cx, p_y0 + 120, font_p_date, GOLD_LIGHT)

    # Місячна декорація
    draw.ellipse([p1_cx - 30, p_y0 + 175, p1_cx + 30, p_y0 + 235], outline=GOLD_MUTED, width=1)
    _draw_star(draw, p1_cx, p_y0 + 205, r_out=18, r_in=5, fill=GOLD_PRIMARY)

    draw.line([(p1_x0 + 20, p_y1 - 65), (p1_x1 - 20, p_y1 - 65)], fill=GOLD_MUTED, width=1)
    font_sub = _get_font(13, bold=False, serif=False)
    _draw_centered_text(draw, "Персональна енергія", p1_cx, p_y1 - 35, font_sub, TEXT_MUTED)

    # Партнер 2 (x0 = 840, x1 = 1120)
    p2_x0, p2_x1 = canvas_w - 80 - p_w, canvas_w - 80
    p2_cx = (p2_x0 + p2_x1) / 2
    _draw_card_box(draw, p2_x0, p_y0, p2_x1, p_y1, card_bg=CARD_BG, border_color=GOLD_SECONDARY, inner_padding=6)

    _draw_centered_text(draw, "✦ ПАРТНЕР 2 ✦", p2_cx, p_y0 + 35, font_partner_tag, GOLD_PRIMARY)

    font_p2_name = _get_font(22 if len(name2) < 14 else 17, bold=True, serif=False)
    _draw_centered_text(draw, name2.upper(), p2_cx, p_y0 + 85, font_p2_name, TEXT_OFFWHITE)

    _draw_centered_text(draw, date2, p2_cx, p_y0 + 120, font_p_date, GOLD_LIGHT)

    # Сонячна декорація
    draw.ellipse([p2_cx - 30, p_y0 + 175, p2_cx + 30, p_y0 + 235], outline=GOLD_MUTED, width=1)
    _draw_star(draw, p2_cx, p_y0 + 205, r_out=18, r_in=5, fill=GOLD_PRIMARY)

    draw.line([(p2_x0 + 20, p_y1 - 65), (p2_x1 - 20, p_y1 - 65)], fill=GOLD_MUTED, width=1)
    _draw_centered_text(draw, "Персональна енергія", p2_cx, p_y1 - 35, font_sub, TEXT_MUTED)

    # 5. Центральна карта: АРКАН СОЮЗУ
    c_w, c_h = 360, 420
    c_x0 = (canvas_w - c_w) // 2
    c_x1 = c_x0 + c_w
    c_y0 = 120
    c_y1 = c_y0 + c_h
    c_cx = canvas_w / 2

    # Сполучні орбіти з боковими картками
    draw.arc([p1_cx, c_y0 - 20, p2_cx, c_y0 + 100], start=180, end=0, fill=GOLD_MUTED, width=1)

    _draw_card_box(draw, c_x0, c_y0, c_x1, c_y1, card_bg=(36, 33, 30), border_color=GOLD_PRIMARY, inner_padding=8)

    font_center_tag = _get_font(14, bold=True, serif=True)
    _draw_centered_text(draw, "✦  А Р К А Н   С О Ю З У  ✦", c_cx, c_y0 + 35, font_center_tag, GOLD_PRIMARY)

    # Велика римська цифра
    font_roman = _get_font(40, bold=True, serif=True)
    _draw_centered_text(draw, to_roman(result_num), c_cx, c_y0 + 95, font_roman, GOLD_LIGHT)

    # Назва Аркана пари
    font_res_name = _get_font(21 if len(result_name) < 18 else 16, bold=True, serif=False)
    _draw_centered_text(draw, result_name.upper(), c_cx, c_y0 + 150, font_res_name, TEXT_OFFWHITE)

    # Символ переплетення сердець / орбіт
    draw.ellipse([c_cx - 45, c_y0 + 210, c_cx + 15, c_y0 + 270], outline=GOLD_PRIMARY, width=2)
    draw.ellipse([c_cx - 15, c_y0 + 210, c_cx + 45, c_y0 + 270], outline=GOLD_PRIMARY, width=2)
    _draw_star(draw, c_cx, c_y0 + 240, r_out=14, r_in=4, fill=GOLD_LIGHT)

    draw.line([(c_x0 + 30, c_y1 - 65), (c_x1 - 30, c_y1 - 65)], fill=GOLD_MUTED, width=1)
    font_center_sub = _get_font(14, bold=False, serif=False)
    _draw_centered_text(draw, "Енергія зв'язку та спільний вектор", c_cx, c_y1 - 35, font_center_sub, GOLD_SECONDARY)

    bio = io.BytesIO()
    img.save(bio, format="JPEG", quality=92, optimize=True)
    return bio.getvalue()


# ---------------------------------------------------------------------------
# 3. ПЕРСОНАЛЬНИЙ АРКАН ДОЛІ (720x1080)
# ---------------------------------------------------------------------------

def render_personal_arcana(
    name: str,
    birth_date: str,
    arc_num: int,
    arc_name: str,
    arc_type: str = "Аркан особистості"
) -> bytes:
    """
    Генерує вертикальну естетичну карточку персонального Аркана (720x1080 px).
    Містить величну центральну карту, символи астрономії та золотий орнамент.
    """
    canvas_w = 720
    canvas_h = 1080
    img = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 1. Зовнішня рамка та зорі
    draw.rectangle([16, 16, canvas_w - 16, canvas_h - 16], outline=GOLD_MUTED, width=1)
    draw.rectangle([20, 20, canvas_w - 20, canvas_h - 20], outline=GOLD_PRIMARY, width=1)
    _draw_background_stars(draw, canvas_w, canvas_h, count=55, seed=333)

    # 2. Заголовок
    font_title = _get_font(28, bold=True, serif=True)
    _draw_centered_text(draw, "✦  Т В І Й   А Р К А Н   Д О Л І  ✦", canvas_w / 2, 65, font_title, GOLD_PRIMARY)

    # Підзаголовок для кого
    font_subtitle = _get_font(18, bold=False, serif=False)
    display_user = f"Для: {name}  ✦  {birth_date}" if name else f"Дата народження: {birth_date}"
    _draw_centered_text(draw, display_user, canvas_w / 2, 105, font_subtitle, TEXT_MUTED)

    # 3. Велична центральна карта
    card_w = 560
    card_h = 800
    x0 = (canvas_w - card_w) // 2
    x1 = x0 + card_w
    y0 = 150
    y1 = y0 + card_h
    cx = canvas_w / 2

    _draw_card_box(draw, x0, y0, x1, y1, card_bg=(34, 31, 29), border_color=GOLD_PRIMARY, inner_padding=10)

    # Тип Аркана
    font_tag = _get_font(15, bold=True, serif=False)
    _draw_centered_text(draw, f"✦  {arc_type.upper()}  ✦", cx, y0 + 45, font_tag, GOLD_SECONDARY)

    # Велика римська цифра
    font_roman = _get_font(52, bold=True, serif=True)
    _draw_centered_text(draw, to_roman(arc_num), cx, y0 + 115, font_roman, GOLD_LIGHT)

    # Назва Аркана
    font_name = _get_font(28 if len(arc_name) < 16 else 22, bold=True, serif=False)
    _draw_centered_text(draw, arc_name.upper(), cx, y0 + 185, font_name, TEXT_OFFWHITE)

    draw.line([(cx - 80, y0 + 225), (cx + 80, y0 + 225)], fill=GOLD_MUTED, width=1)

    # Величний сакральний геометрійний центр
    sym_cy = y0 + 430
    # Велике зовнішнє коло з рисками
    draw.ellipse([cx - 130, sym_cy - 130, cx + 130, sym_cy + 130], outline=GOLD_MUTED, width=1)
    draw.ellipse([cx - 100, sym_cy - 100, cx + 100, sym_cy + 100], outline=GOLD_PRIMARY, width=2)
    draw.ellipse([cx - 65, sym_cy - 65, cx + 65, sym_cy + 65], outline=GOLD_SECONDARY, width=1)

    # Велика 8-кінцева сяюча зірка
    _draw_star(draw, cx, sym_cy, r_out=75, r_in=25, fill=GOLD_PRIMARY)
    _draw_star(draw, cx, sym_cy, r_out=40, r_in=12, fill=GOLD_LIGHT)

    # Ромб навколо кола
    _draw_diamond(draw, cx, sym_cy, w=240, h=240, outline=GOLD_MUTED, width=1)

    # Нижній блок опису енергії
    draw.line([(x0 + 40, y1 - 95), (x1 - 40, y1 - 95)], fill=GOLD_MUTED, width=1)

    font_theme = _get_font(16, bold=False, serif=False)
    _draw_centered_text(draw, "Внутрішній потенціал  ✦  Життєвий вектор", cx, y1 - 60, font_theme, GOLD_SECONDARY)

    # 4. Підпис знизу полотна
    font_footer = _get_font(15, bold=False, serif=False)
    _draw_centered_text(draw, "VELARA tarot & psychology  ✦  @Velara_bot", canvas_w / 2, canvas_h - 40, font_footer, GOLD_SECONDARY)

    bio = io.BytesIO()
    img.save(bio, format="JPEG", quality=92, optimize=True)
    return bio.getvalue()
