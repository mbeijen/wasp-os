{ pkgs ? import <nixpkgs> {} }:

let
  ifLinux = pkgs.lib.optionals pkgs.stdenv.isLinux;

in pkgs.mkShell {
  nativeBuildInputs = [
    # Mirrors pyproject.toml (this shell uses nixpkgs' Python packages
    # rather than uv)
    (pkgs.python3.withPackages (pp: with pp; [
      # Firmware build
      adafruit-nrfutil
      cbor
      click
      cryptography
      intelhex

      # Simulator and tests
      numpy
      pillow
      pysdl2

      pytest

      # Docs
      sphinx

      # wasptool (tools/wasptool): run it as python -m wasptool with
      # PYTHONPATH=tools/wasptool/src
      bleak
    ]))
    pkgs.gcc-arm-embedded-11
    pkgs.graphviz
  ] ++ ifLinux [
    pkgs.bluez
  ];
}
