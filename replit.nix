{ pkgs }: {
  deps = [
    pkgs.ffmpeg
    pkgs.python311
    pkgs.python311Packages.pip
    pkgs.python311Packages.setuptools
    pkgs.libopus
    pkgs.python311Packages.pynacl
  ];
}
