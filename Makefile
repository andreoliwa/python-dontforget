APP_NAME = dontforget
BIN_DIR = $(HOME)/.local/bin
SDKROOT = /Library/Developer/CommandLineTools/SDKs/MacOSX10.15.sdk
CFLAGS = "-isysroot /Library/Developer/CommandLineTools/SDKs/MacOSX10.15.sdk"

build: # Build the project; all these commands below should work (there is no test coverage... ¯\_(ツ)_/¯).
	clear
	pre-commit run --all-files
	poetry run python -m pytest
	poetry run pipe ls
	poetry run pipe run weekly
.PHONY: build

help: # Display this help
	@echo 'Choose one of the following targets:'
	@egrep '^[a-z0-9 ./-]*:.*#' $(lastword $(MAKEFILE_LIST)) | sed -E -e 's/:.+# */@ /g' -e 's/ .+@/@/g' | sort | awk -F@ '{printf "  \033[1;34m%-10s\033[0m %s\n", $$1, $$2}'
.PHONY: help

# https://click.palletsprojects.com/en/7.x/bashcomplete/#activation-script
completion: # Install Bash completion
	$(shell _DONTFORGET_COMPLETE=source_bash poetry run dontforget > dontforget-completion.sh)
	$(shell _FO_COMPLETE=source_bash poetry run fo >> dontforget-completion.sh)
	mkdir -p ~/.local/share/bash-completion/completions/
	ln -fs ${PWD}/dontforget-completion.sh ~/.local/share/bash-completion/completions/
	ls -l ~/.local/share/bash-completion/completions/
	cat ${PWD}/dontforget-completion.sh
.PHONY: completion

install: # Install the project on ~/.local/bin using pipx
ifeq ($(strip $(shell echo $(PATH) | grep $(BIN_DIR) -o)),)
	@echo "The directory $(BIN_DIR) should be in the PATH for this to work. Change your .bashrc or similar file."
	@exit -1
endif
	poetry env use python3.8
	poetry install

	$(MAKE) completion
	pipx uninstall dontforget
	pipx install --verbose .
.PHONY: install

poetry: # Update Poetry
	poetry update
.PHONY: poetry

pre-commit: # Install pre-commit hooks
	pre-commit install --install-hooks
	pre-commit install --hook-type commit-msg
	pre-commit gc
.PHONY: pre-commit

clib: # Force a reinstall of the clib dependency; use when developing locally.
	poetry run pip uninstall --yes clib
	poetry install --no-root
.PHONY: clib
