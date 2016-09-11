#!/bin/sh

# Helper function: readlink substitute (for using in Macs)
# Code from: http://stackoverflow.com/a/1116890

function true_path {(

    TARGET_FILE=$1

    cd `dirname $TARGET_FILE`
    TARGET_FILE=`basename $TARGET_FILE`

    # Iterate down a (possible) chain of symlinks
    while [ -L "$TARGET_FILE" ]
    do
        TARGET_FILE=`readlink $TARGET_FILE`
        cd `dirname $TARGET_FILE`
        TARGET_FILE=`basename $TARGET_FILE`
    done

    # Compute the canonicalized name by finding the physical path 
    # for the directory we're in and appending the target file.
    PHYS_DIR=`pwd -P`
    RESULT=$PHYS_DIR/$TARGET_FILE
    echo $RESULT

)}

# Compute bundle directories

SCRIPT_PATH="$(true_path "$0")"
SCRIPT_NAME="$(basename "$SCRIPT_PATH")"
BUNDLE_MACOS="$(dirname "$SCRIPT_PATH")"
BUNDLE_CONTENTS="$(dirname "$BUNDLE_MACOS")"
BUNDLE="$(dirname "$BUNDLE_CONTENTS")"
BUNDLE_RES="$BUNDLE_CONTENTS/Resources"
BUNDLE_LIB="$BUNDLE_RES/lib"
BUNDLE_BIN="$BUNDLE_RES/bin"
BUNDLE_DATA="$BUNDLE_RES/share"
BUNDLE_ETC="$BUNDLE_RES/etc"

# Export gtk-related environment variables

export DYLD_LIBRARY_PATH="$BUNDLE_LIB"
export XDG_CONFIG_DIRS="$BUNDLE_ETC/xdg"
export XDG_DATA_DIRS="$BUNDLE_DATA"
export GTK_DATA_PREFIX="$BUNDLE_RES"
export GTK_EXE_PREFIX="$BUNDLE_RES"
export GTK_PATH="$BUNDLE_RES"

export PANGO_RC_FILE="$BUNDLE_ETC/pango/pangorc"
export PANGO_SYSCONFDIR="$BUNDLE_ETC"
export PANGO_LIBDIR="$BUNDLE_LIB"

export GDK_PIXBUF_MODULE_FILE="$BUNDLE_LIB/gdk-pixbuf-2.0/2.10.0/loaders.cache"
if [ `uname -r | cut -d . -f 1` -ge 10 ]; then
    export GTK_IM_MODULE_FILE="$BUNDLE_ETC/gtk-3.0/gtk.immodules"
fi

# Configure python

export PYTHON="$BUNDLE_MACOS/python3.4"

PYTHONPATH="$BUNDLE_LIB/python3.4:$PYTHONPATH"
PYTHONPATH="$BUNDLE_LIB/python3.4/site-packages:$PYTHONPATH"
PYTHONPATH="$BUNDLE_RES/opt/app-packages:$PYTHONPATH"
export PYTHONPATH

# Strip out the argument added by the OS.

if /bin/expr "x$1" : "x-psn_.*" > /dev/null; then
    shift 1
fi

# Finally, we execute our python program

# it should be: exec "$PYTHON" -m pulp_gtk

exec "$PYTHON" -m pulp_test
