{
  description = "Ollama-style local text-to-speech for Apple Silicon (Voxtral + Qwen3-TTS, MLX, Nix)";

  inputs = {
    nixpkgs.url = "github:nixOS/nixpkgs/nixpkgs-unstable";

    # Home-Manager input
    home-manager.url = "github:nix-community/home-manager";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    { self, nixpkgs, ... }@inputs:
    let
      systems = [
        "aarch64-darwin"
        "x86_64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];

      forAllSystems =
        function: nixpkgs.lib.genAttrs systems (system: function (import nixpkgs { inherit system; }));
    in
    {
      # === Packages ===
      packages = forAllSystems (
        pkgs:
        let
          ttspeak = pkgs.callPackage ./nix/package.nix { };
        in
        {
          default = ttspeak;
          inherit ttspeak;
        }
      );

      # === Dev Shell: Python + pytest + uv ===
      devShells = forAllSystems (
        pkgs:
        let
          python = pkgs.python312;
        in
        {
          default = pkgs.mkShell {
            packages = [
              python
              pkgs.python312Packages.pytest
              pkgs.uv
              pkgs.ruff
              pkgs.ffmpeg
              pkgs.git
            ];

            shellHook = ''
              export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
              echo "ttspeak dev shell"
              echo "  pytest          run the test suite"
              echo "  python -m ttspeak --help"
            '';
          };
        }
      );

      # === Home-Manager Modul ===
      homeManagerModules.default = import ./nix/module.nix;
      homeManagerModules.ttspeak = self.homeManagerModules.default;

      formatter = forAllSystems (pkgs: pkgs.nixfmt);
    };
}
