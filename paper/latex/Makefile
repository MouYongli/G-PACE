# Build the manuscript. All intermediate files and the PDF go to build/ (git-ignored).
#
#   make            build build/main.pdf with the first available engine:
#                   latexmk, then tectonic, then pdflatex + bibtex
#   make supplement build build/supplement.pdf (supplementary material) the same way
#   make tools      download tectonic into $(PROJECT_ROOT)/.tools/ (no TeX installation needed)
#   make watch      rebuild on every change (latexmk only)
#   make docker     build inside a TeX Live container
#   make clean      remove intermediate files, keep build/main.pdf
#   make distclean  remove build/ entirely
#
# Force an engine with ENGINE=latexmk|tectonic|pdflatex.

MAIN         := main
BUILD_DIR    := build
PDF          := $(BUILD_DIR)/$(MAIN).pdf
TEX_IMAGE    ?= texlive/texlive:latest

# Same resolution order as AGENTS.md: exported PROJECT_ROOT, else the main checkout.
PROJECT_ROOT ?= $(shell dirname "$$(git rev-parse --path-format=absolute --git-common-dir)")

TECTONIC_VERSION := 0.17.0
TECTONIC_DIR     := $(PROJECT_ROOT)/.tools/tectonic
TECTONIC ?= $(if $(wildcard $(TECTONIC_DIR)/tectonic),$(TECTONIC_DIR)/tectonic,tectonic)

has = $(shell command -v $(1) 2>/dev/null)
ENGINE ?= $(if $(call has,latexmk),latexmk,$(if $(call has,$(TECTONIC)),tectonic,pdflatex))

LATEX_OPTS    := -interaction=nonstopmode -halt-on-error -file-line-error -output-directory=$(BUILD_DIR)
LATEXMK_OPTS  := -pdf -outdir=$(BUILD_DIR) -interaction=nonstopmode -halt-on-error -file-line-error
# references.bib and figures/ live in paper/.
TECTONIC_OPTS := -X compile --outdir $(BUILD_DIR) --keep-intermediates --keep-logs -Z search-path=..

# references.bib lives in paper/; llncs.cls and splncs04.bst in this directory.
# Absolute paths, because bibtex runs inside $(BUILD_DIR).
export BIBINPUTS := $(abspath ..):$(CURDIR):$(BIBINPUTS)
export BSTINPUTS := $(CURDIR):$(BSTINPUTS)
export TEXINPUTS := $(CURDIR):$(TEXINPUTS)

SOURCES := $(MAIN).tex macros.tex $(wildcard sections/*.tex) $(wildcard supplement/*.tex) \
           llncs.cls splncs04.bst ../references.bib

.PHONY: all pdf supplement tools watch docker clean distclean

all: pdf

pdf: $(PDF)

supplement:
	$(MAKE) MAIN=supplement pdf

$(PDF): $(SOURCES) | $(BUILD_DIR)
ifeq ($(ENGINE),latexmk)
	latexmk $(LATEXMK_OPTS) $(MAIN).tex
else ifeq ($(ENGINE),tectonic)
	$(TECTONIC) $(TECTONIC_OPTS) $(MAIN).tex
else
	pdflatex $(LATEX_OPTS) $(MAIN).tex
	cd $(BUILD_DIR) && if grep -q '^\\citation' $(MAIN).aux; then bibtex $(MAIN); fi
	pdflatex $(LATEX_OPTS) $(MAIN).tex
	pdflatex $(LATEX_OPTS) $(MAIN).tex
endif

$(BUILD_DIR):
	mkdir -p $@

tools:
	@set -e; \
	case "$$(uname -m)" in \
		x86_64) triple=x86_64-unknown-linux-musl ;; \
		aarch64|arm64) triple=aarch64-unknown-linux-musl ;; \
		*) echo "unsupported architecture: $$(uname -m)" >&2; exit 1 ;; \
	esac; \
	url="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40$(TECTONIC_VERSION)/tectonic-$(TECTONIC_VERSION)-$$triple.tar.gz"; \
	mkdir -p "$(TECTONIC_DIR)"; \
	echo "downloading $$url"; \
	curl -fsSL "$$url" | tar -xz -C "$(TECTONIC_DIR)" tectonic; \
	"$(TECTONIC_DIR)/tectonic" --version

watch: | $(BUILD_DIR)
	latexmk $(LATEXMK_OPTS) -pvc $(MAIN).tex

# Mount paper/ so ../references.bib and ../figures/ resolve inside the container.
docker: | $(BUILD_DIR)
	docker run --rm -u $$(id -u):$$(id -g) -v "$(abspath ..)":/paper -w /paper/latex \
		$(TEX_IMAGE) make pdf ENGINE=latexmk

clean:
	@if [ -d $(BUILD_DIR) ]; then \
		find $(BUILD_DIR) -mindepth 1 ! -name '$(MAIN).pdf' -delete; \
	fi

distclean:
	rm -rf $(BUILD_DIR)
