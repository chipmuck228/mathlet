"""Reuse saved font settings without running against the interactive Office profile."""
import copy
import os
from pathlib import Path
import shutil
import sys

from lxml import etree as ET

OOR = 'http://openoffice.org/2001/registry'


def saved_user_profile():
    configured = os.environ.get('MATHLET_LIBREOFFICE_PROFILE')
    if configured:
        path = Path(configured).expanduser()
        user = path if path.name == 'user' else path / 'user'
        if not user.is_dir():
            raise ValueError('MATHLET_LIBREOFFICE_PROFILE 不是有效配置目录：请选择包含 user 子目录的 LibreOffice/4 目录，或 user 目录本身')
        return user
    if sys.platform == 'darwin':
        path = Path.home() / 'Library/Application Support/LibreOffice/4/user'
    elif sys.platform == 'win32':
        path = Path(os.environ.get('APPDATA', str(Path.home() / 'AppData/Roaming'))) / 'LibreOffice/4/user'
    else:
        path = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'libreoffice/4/user'
    return path if path.is_dir() else None


def seed_font_settings(destination: Path):
    """Read only font/language items; never copy macros, locks, recent files or credentials."""
    source = saved_user_profile()
    if source is None:
        return '未发现已保存的 LibreOffice 用户配置，使用系统字体'
    user = destination / 'user'
    user.mkdir(parents=True, exist_ok=True)
    registry = source / 'registrymodifications.xcu'
    count = 0
    if registry.is_file():
        parser = ET.XMLParser(resolve_entities=False, no_network=True)
        tree = ET.parse(str(registry), parser)
        root = ET.Element(f'{{{OOR}}}items', nsmap={'oor': OOR, 'xs': 'http://www.w3.org/2001/XMLSchema', 'xsi': 'http://www.w3.org/2001/XMLSchema-instance'})
        for item in tree.getroot():
            path = item.get(f'{{{OOR}}}path', '')
            if any(token in path for token in ('/Font', '/DefaultFont', '/L10N', '/I18N', 'Office.Linguistic')):
                root.append(copy.deepcopy(item))
                count += 1
        ET.ElementTree(root).write(str(user / 'registrymodifications.xcu'), encoding='UTF-8', xml_declaration=True)
    fonts = source / 'fonts'
    font_count = 0
    if fonts.is_dir():
        for font in fonts.rglob('*'):
            if font.is_file() and not font.is_symlink() and font.suffix.lower() in {'.ttf', '.otf', '.ttc', '.otc'}:
                target = user / 'fonts' / font.relative_to(fonts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(font, target)
                font_count += 1
    return f'已沿用本机 {count} 项字体／语言配置及 {font_count} 个配置目录字体；请核对中文显示'
