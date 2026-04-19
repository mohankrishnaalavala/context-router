# context-router Homebrew Formula — TEMPLATE
#
# This file is the source of truth for the formula. It is a TEMPLATE: the
# version/sha256 tokens (double-brace style, see url/sha256/version below)
# are substituted at release time by scripts/render_homebrew_formula.py
# (invoked from the `homebrew-publish` job in .github/workflows/release.yml).
#
# The live, rendered formula is committed to the tap repo:
#   https://github.com/mohankrishnaalavala/homebrew-context-router
#
# DO NOT `brew install` this file directly — the placeholders will fail to
# parse. Users install the rendered formula via the tap:
#   brew tap mohankrishnaalavala/context-router
#   brew install context-router

class ContextRouter < Formula
  include Language::Python::Virtualenv

  desc "Minimum-context selector for AI coding agents — MCP server + CLI"
  homepage "https://github.com/mohankrishnaalavala/context-router"
  url "https://github.com/mohankrishnaalavala/context-router/archive/refs/tags/v{{VERSION}}.tar.gz"
  sha256 "{{SHA256}}"
  license "MIT"
  version "{{VERSION}}"

  depends_on "python@3.12"

  # Core dependencies — regenerate with:
  #   pip install context-router-cli --dry-run 2>&1 | grep -v context-router
  resource "annotated-types" do
    url "https://files.pythonhosted.org/packages/source/a/annotated_types/annotated_types-0.7.0.tar.gz"
    sha256 "aff07c09a53a08bc8cfccb9c85b05f1aa9a2a6f23728d790723543408344ce89"
  end

  resource "click" do
    url "https://files.pythonhosted.org/packages/source/c/click/click-8.1.8.tar.gz"
    sha256 "ed53c9d8992d59191a698c65d3e4fae48be8e2d4f4c37c5e43c5c2bd8dba4a08"
  end

  resource "pydantic" do
    url "https://files.pythonhosted.org/packages/source/p/pydantic/pydantic-2.11.3.tar.gz"
    sha256 "7471657138c16adad9322fe3070c0116dd6c3ad8d649300e3cbdfe91f4db4ec3"
  end

  resource "pydantic-core" do
    url "https://files.pythonhosted.org/packages/source/p/pydantic_core/pydantic_core-2.33.1.tar.gz"
    sha256 "bcc9c6fdb0ced789245b02b7d6603e17d1563064ddcfc36f046b61c0c05dd9df"
  end

  resource "tiktoken" do
    url "https://files.pythonhosted.org/packages/source/t/tiktoken/tiktoken-0.9.0.tar.gz"
    sha256 "d02a5ca6a938e0490bf338c7ec39f3060c75dc39e1c9c9e2e21b4e0fb8f87e4b"
  end

  resource "typer" do
    url "https://files.pythonhosted.org/packages/source/t/typer/typer-0.15.3.tar.gz"
    sha256 "2c1a3b3e4dd5f3c0eda5009a7e0285a96e71a21c1e038f54d8d1b30f59a74f81"
  end

  resource "watchdog" do
    url "https://files.pythonhosted.org/packages/source/w/watchdog/watchdog-6.0.0.tar.gz"
    sha256 "9ddf7c82fda3ae8e24decda1338ede66e1c99883db93711d8fb941eaa2d8c282"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "context-router", shell_output("#{bin}/context-router --help")
    assert_match version.to_s, shell_output("#{bin}/context-router --version")
  end
end
