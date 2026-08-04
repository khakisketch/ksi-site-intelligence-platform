#include "logger_console_glue.h"

#include <dji_logger.h>
#include <dji_platform.h>

#include <stdio.h>

static T_DjiReturnCode KsiLoggerConsole_Write(const uint8_t *data, uint16_t dataLen)
{
    fwrite(data, 1, dataLen, stderr);
    return DJI_ERROR_SYSTEM_MODULE_CODE_SUCCESS;
}

T_DjiReturnCode KsiLoggerConsoleGlue_Register(void)
{
    T_DjiLoggerConsole console = {
        .func = KsiLoggerConsole_Write,
        .consoleLevel = DJI_LOGGER_CONSOLE_LOG_LEVEL_INFO,
        .isSupportColor = false,
    };
    return DjiLogger_AddConsole(&console);
}
