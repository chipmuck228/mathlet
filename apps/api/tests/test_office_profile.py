from pathlib import Path
import pytest
from mathlet.office_profile import seed_font_settings, saved_user_profile
from lxml import etree as ET


def test_only_font_and_language_settings_are_inherited_without_touching_source(tmp_path, monkeypatch):
    source = tmp_path / 'saved' / 'user'; source.mkdir(parents=True)
    original = b'''<oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Font/Substitution"><prop oor:name="Replacement"><value>Noto Sans CJK SC</value></prop></item><item oor:path="/org.openoffice.Office.Writer/DefaultFontCJK"><prop oor:name="Standard"><value>Noto Serif CJK SC</value></prop></item><item oor:path="/org.openoffice.Setup/L10N"><prop oor:name="ooLocale"><value>zh-CN</value></prop></item><item oor:path="/org.openoffice.Office.Histories"><prop oor:name="Recent"><value>private.docx</value></prop></item></oor:items>'''
    (source / 'registrymodifications.xcu').write_bytes(original)
    (source / 'fonts').mkdir(); (source / 'fonts' / 'test.ttf').write_bytes(b'font fixture')
    (source / 'basic').mkdir(); (source / 'basic' / 'macro').write_text('private macro')
    monkeypatch.setenv('MATHLET_LIBREOFFICE_PROFILE', str(source.parent))
    target = tmp_path / 'isolated'
    note = seed_font_settings(target)
    output = (target / 'user/registrymodifications.xcu').read_text()
    assert len(ET.fromstring(output.encode())) == 3
    assert 'Noto Sans CJK SC' in output and 'zh-CN' in output
    assert 'private.docx' not in output
    assert not (target / 'user/basic').exists()
    assert (target / 'user/fonts/test.ttf').read_bytes() == b'font fixture'
    assert (source / 'registrymodifications.xcu').read_bytes() == original
    assert '3' in note
    monkeypatch.setenv('MATHLET_LIBREOFFICE_PROFILE', str(source))
    assert saved_user_profile() == source


def test_missing_default_is_explicit_but_invalid_override_is_not_silently_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv('MATHLET_LIBREOFFICE_PROFILE', raising=False)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    assert '未发现' in seed_font_settings(tmp_path / 'temp')
    monkeypatch.setenv('MATHLET_LIBREOFFICE_PROFILE', str(tmp_path / 'missing'))
    with pytest.raises(ValueError, match='不是有效配置目录'):
        seed_font_settings(tmp_path / 'temp')


def test_macos_prefers_gui_application_over_an_unrelated_path_install(monkeypatch):
    from mathlet import original_view
    monkeypatch.delenv('MATHLET_SOFFICE', raising=False)
    monkeypatch.setattr(original_view.sys, 'platform', 'darwin')
    expected = '/Applications/LibreOffice.app/Contents/MacOS/soffice'
    monkeypatch.setattr(Path, 'is_file', lambda path: str(path) == expected)
    monkeypatch.setattr(original_view.shutil, 'which', lambda _: '/another/soffice')
    assert original_view.converter() == expected
