{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.ttspeak;

  # Base models for cloned voices are installed automatically.
  voiceModels = lib.mapAttrsToList (_: voice: voice.model) cfg.voices;
  requiredModels = lib.unique (cfg.models ++ voiceModels);

  defaultsFile = pkgs.writeText "ttspeak-defaults.json" (builtins.toJSON cfg.settings);

  shellEscape = lib.escapeShellArg;

  runStep =
    description: command:
    if cfg.onActivation.failOnError then
      command
    else
      "(${command}) || echo ${shellEscape "ttspeak: warning: ${description} failed"} >&2";

  keepModels = lib.concatMapStringsSep " " shellEscape requiredModels;

  # === Install declared models (like `brew bundle`) ===
  pullModels = lib.concatMapStringsSep "\n" (
    model:
    lib.optionalString (model != "") ''
      ${runStep "pulling ${model}" "$DRY_RUN_CMD ${cfg.package}/bin/ttspeak pull ${shellEscape model}"}
    ''
  ) requiredModels;

  # === Create declared cloned voices ===
  createVoices = lib.concatStringsSep "\n" (
    lib.mapAttrsToList (
      name: voice:
      let
        command =
          "$DRY_RUN_CMD ${cfg.package}/bin/ttspeak voice add ${shellEscape name} "
          + "--audio ${shellEscape (toString voice.audio)} "
          + "--text ${shellEscape voice.text} "
          + "--model ${shellEscape voice.model} --force";
      in
      runStep "creating voice ${name}" command
    ) cfg.voices
  );

  # === Clean up like `brew bundle cleanup --force` (zap) ===
  zapModels = lib.optionalString (cfg.onActivation.cleanup == "zap") ''
    ${runStep "pruning models" "$DRY_RUN_CMD ${cfg.package}/bin/ttspeak prune --yes${
      lib.optionalString (requiredModels != [ ]) " --keep ${keepModels}"
    }"}
  '';

  zapVoices = lib.optionalString (cfg.onActivation.cleanup == "zap") ''
    ${runStep "pruning voices" "$DRY_RUN_CMD ${cfg.package}/bin/ttspeak voice prune --yes${
      lib.optionalString (cfg.voices != { })
        " --keep ${lib.concatMapStringsSep " " shellEscape (lib.attrNames cfg.voices)}"
    }"}
  '';
in
{
  options.programs.ttspeak = {
    enable = lib.mkEnableOption "ttspeak local text-to-speech";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ./package.nix { }";
      description = "The ttspeak package to install.";
    };

    settings = lib.mkOption {
      type = lib.types.attrsOf lib.types.anything;
      default = { };
      example = {
        model = "voxtral:4b";
        language = "auto";
        default_gender = "female";
        voices = {
          de = "de_female";
          de_female = {
            model = "voxtral:4b";
            voice = "de_female";
          };
          ru = "ru_female";
          ru_female = {
            model = "qwen3:1.7b";
            voice = "Sohee";
          };
        };
        speed = 1.0;
      };
      description = ''
        Declarative defaults, exported through TTSPEAK_DEFAULTS. Values may be
        scalars, lists or nested attrsets (for `voices`). The mutable user
        configuration (`ttspeak config set`) still takes precedence.
      '';
    };

    models = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "qwen3:0.6b" ];
      description = "Models pulled on Home Manager activation (idempotent).";
    };

    voices = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            audio = lib.mkOption {
              type = lib.types.path;
              description = "Reference WAV recording.";
            };
            text = lib.mkOption {
              type = lib.types.str;
              description = "Exact transcript of the reference recording.";
            };
            model = lib.mkOption {
              type = lib.types.str;
              default = "qwen3:0.6b-base";
              description = "Base (cloning) model; pulled automatically.";
            };
          };
        }
      );
      default = { };
      description = "Cloned voice profiles created on activation.";
    };

    runtime.enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Install the isolated MLX runtime (mlx-audio) if it is missing.";
    };

    ffmpeg = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Install ffmpeg for MP3/FLAC/OGG/Opus/M4A output.";
    };

    runtime.python = lib.mkOption {
      type = lib.types.package;
      default = pkgs.python312;
      defaultText = lib.literalExpression "pkgs.python312";
      description = "Python interpreter used to create the runtime venv.";
    };

    runtime.version = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "0.6.2";
      description = "Pin the mlx-audio version; null installs the latest prerelease.";
    };

    onActivation = {
      cleanup = lib.mkOption {
        type = lib.types.enum [
          "none"
          "zap"
        ];
        default = "none";
        example = "zap";
        description = ''
          "zap" removes installed models and voice profiles that are not declared
          here, similar to `homebrew.onActivation.cleanup = "zap"`.
        '';
      };

      failOnError = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Fail home-manager switch when a pull/runtime step fails. Default: warn and continue.";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    # runtime.python is referenced by absolute store path for the venv. Do not
    # link it into the profile: two Python versions collide on bin/idle.
    home.packages = [
      cfg.package
    ]
    ++ lib.optional cfg.ffmpeg pkgs.ffmpeg
    ++ lib.optional cfg.runtime.enable pkgs.uv;

    home.sessionVariables = lib.mkIf (cfg.settings != { }) {
      TTSPEAK_DEFAULTS = "${defaultsFile}";
    };

    # === Activation: runtime, models, voices, optional zap ===
    home.activation.ttspeak = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      export PATH="${
        lib.makeBinPath (
          [
            cfg.package
            pkgs.uv
          ]
          ++ lib.optional cfg.runtime.enable cfg.runtime.python
        )
      }:$PATH"

      ${lib.optionalString cfg.runtime.enable ''
        ${runStep "installing the MLX runtime" "$DRY_RUN_CMD ${cfg.package}/bin/ttspeak runtime install --python ${shellEscape "${cfg.runtime.python}/bin/python3"}${
          lib.optionalString (cfg.runtime.version != null) " --version ${shellEscape cfg.runtime.version}"
        }"}
      ''}

      ${pullModels}
      ${createVoices}
      ${zapModels}
      ${zapVoices}
    '';
  };
}
