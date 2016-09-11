
APP        = Pulp
MODULE_DIR = pulp_gtk
MAC_SRC    = macosx
BUILD_DIR  = build

########################################################################

.PHONY: default clean clean-noconfirm

default:
	@echo Make what?

clean:
	@echo This will erase all contents of the build directory.
	@read -r -p "Confirm action? [y/N] " CONFIRM; \
	    if [ "$$CONFIRM" = "y" -o "$$CONFIRM" = "Y" ]; then \
	    	rm -r "$(BUILD_DIR)"; \
	    	echo "Build directory erased."; \
	    else \
		echo "Action canceled. Build directory not erased."; \
	    fi

clean-noconfirm:
	-rm -r "$(BUILD_DIR)"

########################################################################

MAC_APP         = $(BUILD_DIR)/$(APP).app
MAC_BUNDLE_FILE = $(MAC_SRC)/$(APP).bundle
MAC_GTK_MODULES = meta-gtk-osx-gtk3 \
		  python3 \
		  meta-gtk-osx-python3-gtk3

MAC_AUX_DIR     = $(BUILD_DIR)/aux
MAC_PHONY_DIR   = $(MAC_AUX_DIR)/.phony
MAC_BUILD_DIRS  = $(MAC_PHONY_DIR)/dirs
MAC_JAIL_BIN    = $(MAC_AUX_DIR)/.local/bin
MAC_JAIL        = $(MAC_JAIL_BIN)/gtk-jail
MAC_BUILD_SETUP = $(MAC_JAIL_BIN)/gtk-osx-build-setup.sh
MAC_BUNDLER     = $(MAC_JAIL_BIN)/gtk-mac-bundler
MAC_JHBUILD     = $(MAC_PHONY_DIR)/jhbuild
MAC_GTK         = $(MAC_PHONY_DIR)/gtk
MAC_GTK_EVINCE  = $(MAC_PHONY_DIR)/gtk_evince
MAC_BASEURL     = "https://git.gnome.org/browse/gtk-osx/plain"

.PHONY: jhbuild gtk gtk_modules evince bundler mac_app

jhbuild:     $(MAC_JHBUILD)
gtk:         $(MAC_GTK)
gtk_modules:
evince:      $(MAC_GTK_EVINCE)
bundler:     $(MAC_BUNDLER)
mac_app:     $(MAC_APP)

define build_print
	@echo -en '\e[1;34m'
	@printf '=%.0s' {1..80}
	@echo
	@echo "=" "$1" 
	@printf '=%.0s' {1..80}
	@echo -e '\e[0m'
	@echo
endef

$(MAC_BUILD_DIRS): 
	$(call build_print, Creating directory structure for build jail)
	mkdir -p "$(MAC_PHONY_DIR)"/modules
	mkdir -p "$(MAC_JAIL_BIN)"
	@touch "$(MAC_BUILD_DIRS)"
	@echo

$(MAC_JAIL): $(MAC_SRC)/gtk-jail $(MAC_BUILD_DIRS)
	$(call build_print, Copying script gtk-jail)
	cp "$<" "$@"
	@echo

$(MAC_BUILD_SETUP): $(MAC_BUILD_DIRS)
	$(call build_print, Downloading script gtk-osx-build-setup.sh)
	curl -ks "$(MAC_BASEURL)/gtk-osx-build-setup.sh" -o "$@"
	chmod +x "$@"
	@echo

$(MAC_JHBUILD): $(MAC_JAIL) $(MAC_BUILD_SETUP)
	$(call build_print, Installing jhbuild in build jail)
	"$(MAC_JAIL)" bash -c 'cd "$(MAC_AUX_DIR)"; gtk-osx-build-setup.sh'
	@touch "$(MAC_JHBUILD)"
	@echo

define jhbuild_call
	$(call build_print, Running jhbuild $1)
	"$(MAC_JAIL)" jhbuild $1
	@echo
endef

$(MAC_GTK): $(MAC_JHBUILD)
	$(call jhbuild_call, bootstrap)
	$(call jhbuild_call, build meta-gtk-osx-bootstrap)
	@touch "$(MAC_GTK)"

define GTK_MODULE_template
gtk_modules: $(MAC_PHONY_DIR)/modules/$(1)
$(MAC_PHONY_DIR)/modules/$(1): $(MAC_GTK)
	$$(call jhbuild_call, build $(1))
	@touch "$(MAC_PHONY_DIR)/modules/$(1)"
	@echo
endef

$(foreach module,$(MAC_GTK_MODULES),$(eval $(call GTK_MODULE_template,$(module))))

$(MAC_GTK_EVINCE): gtk_modules
	$(call jhbuild_call, -m gnome-apps-3.20.modules build evince)
	@touch "$(MAC_GTK_EVINCE)"

$(MAC_BUNDLER): $(MAC_JAIL)
	$(call build_print, Downloading gtk-mac-bundler)
	cd "$(MAC_AUX_DIR)"; git clone git://git.gnome.org/gtk-mac-bundler
	"$(MAC_JAIL)" bash -c 'cd "$(MAC_AUX_DIR)/gtk-mac-bundler"; make install'
	@echo

.PHONY: $(MAC_APP)
$(MAC_APP): $(MAC_BUNDLER) gtk_modules
	$(call build_print, Creating app bundle)
	"$(MAC_JAIL)" jhbuild run gtk-mac-bundler "$(MAC_BUNDLE_FILE)"
	@echo
