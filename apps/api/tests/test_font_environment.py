import os
from pathlib import Path
from lxml import etree as ET
import pytest
from mathlet import font_environment as fonts


def test_macos_reads_host_directories_and_rules_in_child_only(tmp_path, monkeypatch):
    monkeypatch.setattr(fonts.sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'account')
    monkeypatch.delenv('FONTCONFIG_FILE', raising=False)
    monkeypatch.delenv('FONTCONFIG_PATH', raising=False)
    executable = tmp_path / 'LibreOffice.app/Contents/MacOS/soffice'
    bundled = executable.parent.parent / 'Resources/fontconfig/fonts.conf'
    bundled.parent.mkdir(parents=True); bundled.write_text('<fontconfig/>')
    work = tmp_path / 'conversion'; work.mkdir()
    env, note = fonts.conversion_environment(str(executable), work)
    root = ET.parse(env['FONTCONFIG_FILE'])
    assert root.findtext('include') == str(bundled)
    dirs = root.xpath('/fontconfig/dir/text()')
    assert '/System/Library/Fonts' in dirs and '/System/Library/AssetsV2' in dirs
    assert str(tmp_path / 'account/Library/Fonts') in dirs
    assert env['FONTCONFIG_PATH'] == str(bundled.parent)
    assert 'FONTCONFIG_FILE' not in os.environ
    assert 'macOS' in note


def test_respects_supplied_rules_but_rejects_missing_config(tmp_path, monkeypatch):
    monkeypatch.setattr(fonts.sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    base = tmp_path / 'my-fonts.conf'; base.write_text('<fontconfig/>')
    monkeypatch.setenv('FONTCONFIG_FILE', str(base))
    env, _ = fonts.conversion_environment('/test/soffice', tmp_path)
    assert ET.parse(env['FONTCONFIG_FILE']).findtext('include') == str(base)
    monkeypatch.setenv('FONTCONFIG_FILE', str(tmp_path / 'missing'))
    with pytest.raises(ValueError, match='不存在'):
        fonts.conversion_environment('/test/soffice', tmp_path)


def test_other_platforms_keep_existing_font_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(fonts.sys, 'platform', 'linux')
    monkeypatch.setenv('FONTCONFIG_FILE', '/existing/fontconfig')
    env, note = fonts.conversion_environment('/test/soffice', tmp_path)
    assert env['FONTCONFIG_FILE'] == '/existing/fontconfig' and note == ''


def test_rejects_observed_missing_cjk_signature_but_not_valid_cjk_or_latin_only():
    from types import SimpleNamespace
    class Font(dict):
        def get_object(self): return self
    class Page(dict):
        def extract_text(self): return self.text
    page = Page({'/Resources': {'/Font': {'/F1': Font({'/BaseFont': '/ABCDEF+LinuxLibertineG'})}}})
    page.text = '中文仍可复制，但字形丢失'
    reader = SimpleNamespace(pages=[page])
    with pytest.raises(ValueError, match='本次 PDF 未采用'):
        fonts.reject_known_missing_cjk(reader)
    page['/Resources']['/Font']['/F2'] = Font({'/BaseFont': '/ABCDEF+PingFangSC-Regular'})
    fonts.reject_known_missing_cjk(reader)
    del page['/Resources']['/Font']['/F2']
    page.text = 'English text only'
    fonts.reject_known_missing_cjk(reader)
