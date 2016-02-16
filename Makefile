
APP_NAME   = Pulp
MODULE_DIR = pulp_gtk
AUX_DIR    = pulp_app

BUILD_DIR         = build
APP_DIR           = ${BUILD_DIR}/${APP_NAME}.app
CONTENTS_DIR      = ${APP_DIR}/Contents
BIN_DIR           = ${CONTENTS_DIR}/MacOS
RESOURCES_DIR     = ${CONTENTS_DIR}/Resources
TARGET_MODULE_DIR = ${RESOURCES_DIR}/${MODULE_DIR}

MODULE_SOURCES = $(wildcard ${MODULE_DIR}/*.*)

MODULE_TARGETS = ${MODULE_SOURCES:${MODULE_DIR}/%=${TARGET_MODULE_DIR}/%}

TARGETS = ${CONTENTS_DIR}/Info.plist \
          ${BIN_DIR}/pulp.exe \
          ${RESOURCES_DIR}/orange_slice.icns \
          ${MODULE_TARGETS}

default: ${TARGETS}

echo_targets:
	@for i in ${TARGETS}; do echo $$i; done 

${CONTENTS_DIR}/Info.plist: ${AUX_DIR}/Info.plist
	@echo $@
	@mkdir -p '${CONTENTS_DIR}'
	@cp $< $@

${BIN_DIR}/pulp.exe: ${AUX_DIR}/pulp.exe
	@echo $@
	@mkdir -p '${BIN_DIR}'
	@cp $< $@
	@chmod +x $@

${RESOURCES_DIR}/orange_slice.icns: ${AUX_DIR}/orange_slice.icns
	@echo $@
	@mkdir -p '${RESOURCES_DIR}'
	@cp $< $@

${TARGET_MODULE_DIR}/%: ${MODULE_DIR}/%
	@echo $@
	@mkdir -p '${TARGET_MODULE_DIR}'
	@cp $< $@

clean:
	-rm -r ${BUILD_DIR}
