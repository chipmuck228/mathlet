"""Explicit host-font discovery for macOS headless LibreOffice."""
import os
from pathlib import Path
import sys
from lxml import etree as ET


def conversion_environment(executable: str, work: Path):
    env = os.environ.copy()
    if sys.platform != 'darwin':
        return env, ''
    supplied = env.get('FONTCONFIG_FILE')
    resources = Path(executable).resolve().parent.parent / 'Resources'
    candidates = ([Path(supplied).expanduser()] if supplied else []) + [
        resources / 'fontconfig/fonts.conf',
        Path('/opt/homebrew/etc/fonts/fonts.conf'),
        Path('/usr/local/etc/fonts/fonts.conf'),
    ]
    if supplied and not candidates[0].is_file():
        raise ValueError('FONTCONFIG_FILE 指向不存在的文件，请修正该环境变量后重启工作台')
    base = next((p for p in candidates if p.is_file()), None)
    root = ET.Element('fontconfig')
    if base:
        ET.SubElement(root, 'include', ignore_missing='yes').text = str(base.resolve())
    # Use absolute host paths: never depend on a temporary profile's HOME.
    for directory in [Path('/System/Library/Fonts'), Path('/System/Library/Assets'),
                      Path('/System/Library/AssetsV2'), Path('/Library/Fonts'),
                      Path.home() / 'Library/Fonts', resources / 'fonts/truetype']:
        ET.SubElement(root, 'dir').text = str(directory)
    cache = Path.home() / 'Library/Caches/mathlet/fontconfig'
    cache.mkdir(parents=True, exist_ok=True)
    ET.SubElement(root, 'cachedir').text = str(cache)
    # Weak defaults preserve an installed requested font; only provide fallbacks.
    for family, fallback in [('serif', 'Songti SC'), ('sans-serif', 'PingFang SC'),
                             ('SimSun', 'Songti SC'), ('宋体', 'Songti SC'),
                             ('SimHei', 'Heiti SC'), ('黑体', 'Heiti SC'),
                             ('Microsoft YaHei', 'PingFang SC')]:
        alias = ET.SubElement(root, 'alias', binding='weak')
        ET.SubElement(alias, 'family').text = family
        ET.SubElement(ET.SubElement(alias, 'default'), 'family').text = fallback
    config = work / 'fonts.conf'
    ET.ElementTree(root).write(str(config), encoding='UTF-8', xml_declaration=True)
    env['FONTCONFIG_FILE'] = str(config.resolve())
    env['FONTCONFIG_PATH'] = str(base.resolve().parent if base else work.resolve())
    return env, '；已显式启用 macOS 系统中文字体目录与 Fontconfig 规则'


def reject_known_missing_cjk(reader):
    """Catch the observed Latin-only fallback signature; not a general glyph validator."""
    families = set()
    has_chinese = False
    for page in reader.pages:
        if not has_chinese:
            has_chinese = any('\u3400' <= c <= '\u9fff' for c in (page.extract_text() or ''))
        for font in page.get('/Resources', {}).get('/Font', {}).values():
            name = str(font.get_object().get('/BaseFont', '')).split('+')[-1].lstrip('/')
            if name:
                families.add(name)
    known_fallbacks = ('LinuxLibertineG', 'FrankRuhlHofshi', 'Carlito')
    if has_chinese and families and all(name.startswith(known_fallbacks) for name in families):
        raise ValueError('检测到与缺字样本相同的中文／西文字体回退异常，本次 PDF 未采用。请检查 macOS Fontconfig 字体配置；已有预览保留。')
