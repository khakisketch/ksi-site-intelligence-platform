# Shared PSDK platform glue used by the diagnostic tap and the production DPK.
#
# The Linux/Manifold implementation remains one source of truth in
# edge/psdk-tap/src/platform.  This module is an intentional extraction of its
# build ownership: a second PSDK app links exactly those same OSAL, socket,
# USB-bulk, and logger handlers instead of copying a subtly divergent version.
# In particular it does *not* change the unverified Manifold USB channel map;
# HIL must establish that map from inside an installed DPK.

set(KSI_PSDK_PLATFORM_MODULE_DIR "${CMAKE_CURRENT_LIST_DIR}")

function(ksi_add_psdk_platform_glue target)
  if(NOT TARGET "${target}")
    message(FATAL_ERROR "ksi_add_psdk_platform_glue: unknown target ${target}")
  endif()

  set(_platform_source_root "${KSI_PSDK_PLATFORM_MODULE_DIR}/../psdk-tap/src/platform")
  target_sources("${target}" PRIVATE
    "${_platform_source_root}/osal_glue.c"
    "${_platform_source_root}/socket_glue.c"
    "${_platform_source_root}/usb_bulk_glue.c"
    "${_platform_source_root}/logger_console_glue.c"
  )
  # The public glue headers are intentionally included as "platform/foo.h";
  # make the tap source root available to both owners without duplicating it.
  target_include_directories("${target}" PRIVATE
    "${KSI_PSDK_PLATFORM_MODULE_DIR}/../psdk-tap/src"
  )
endfunction()
