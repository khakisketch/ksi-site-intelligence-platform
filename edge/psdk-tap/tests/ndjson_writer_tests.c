/* ndjson_writer v2 contract test — PSDK/hardware 없이 raw-timestamp isolation을 검증한다. */
#include "psdk_tap/ndjson_writer.h"

#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int g_checks = 0;
static int g_failures = 0;

static void Check(bool condition, const char *what)
{
    g_checks += 1;
    if (!condition) {
        g_failures += 1;
        fprintf(stderr, "FAIL: %s\n", what);
    }
}

static char *ReadAll(const char *path)
{
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return NULL;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return NULL;
    }
    long size = ftell(file);
    if (size < 0 || fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        return NULL;
    }
    char *contents = calloc((size_t) size + 1U, 1U);
    if (contents == NULL) {
        fclose(file);
        return NULL;
    }
    if (fread(contents, 1U, (size_t) size, file) != (size_t) size) {
        free(contents);
        fclose(file);
        return NULL;
    }
    fclose(file);
    return contents;
}

int main(void)
{
    char path[] = "/tmp/ksi-psdk-tap-ndjson-XXXXXX";
    int fd = mkstemp(path);
    Check(fd >= 0, "temporary output path를 만든다");
    if (fd < 0) {
        return 1;
    }
    close(fd);

    ksi_ndjson_writer_t writer;
    Check(ksi_ndjson_open(&writer, path), "writer를 연다");
    if (writer.file == NULL) {
        unlink(path);
        return 1;
    }

    ksi_ndjson_write_meta(&writer, 2, "3.16.0", "2026-08-14T00:00:00Z", "SN-TEST", 123,
                           "2026-08-14T00:00:00Z", false, true, "perception_grayscale",
                           "perception_image_info_timestamp_raw_unverified", "unverified");

    ksi_ndjson_endpoint_t frame = {
        .recv_mono_ns = 456,
        .has_sensor_us = false,
        .sensor_us = 0,
        .has_sensor_timestamp_raw_u64 = true,
        .sensor_timestamp_raw_u64 = UINT64_MAX,
        .has_perception_metadata = true,
        .perception_data_id = 7,
        .perception_sequence = 8,
        .perception_data_type = 9,
        .perception_raw_index = 10,
        .perception_raw_direction = 1,
        .perception_bpp = 8,
        .perception_width = 640,
        .perception_height = 480,
        .perception_buffer_len = 614400,
    };
    ksi_ndjson_endpoint_t telemetry = {
        .recv_mono_ns = 457,
        .has_sensor_us = true,
        .sensor_us = 99,
        .has_sensor_timestamp_raw_u64 = false,
        .sensor_timestamp_raw_u64 = 0,
        .has_perception_metadata = false,
        .perception_data_id = 0,
        .perception_sequence = 0,
        .perception_data_type = 0,
        .perception_raw_index = 0,
        .perception_raw_direction = 0,
        .perception_bpp = 0,
        .perception_width = 0,
        .perception_height = 0,
        .perception_buffer_len = 0,
    };
    ksi_ndjson_write_sample(&writer, 0, frame, telemetry, true, true, "nearest_recv_mono_ns", -1);
    ksi_ndjson_close(&writer);

    char *contents = ReadAll(path);
    Check(contents != NULL, "기록된 NDJSON을 읽는다");
    if (contents != NULL) {
        Check(strstr(contents, "\"frame_source\":\"perception_grayscale\"") != NULL,
              "meta가 perception source를 식별한다");
        Check(strstr(contents, "\"frame_sensor_ts\":false") != NULL,
              "raw timestamp가 frame sensor capability를 승격하지 않는다");
        Check(strstr(contents, "\"sensor_us_domain\":\"unverified\"") != NULL,
              "sensor_us clock domain을 unverified로 기록한다");
        Check(strstr(contents, "\"sensor_us\":null,\"sensor_timestamp_raw_u64\":\"18446744073709551615\"") !=
                  NULL,
              "uint64 raw timestamp를 lossless string으로 격리한다");
        Check(strstr(contents, "\"perception\":{\"data_id\":7,\"sequence\":8") != NULL,
              "perception callback metadata를 함께 기록한다");
        free(contents);
    }
    unlink(path);

    printf("ndjson_writer_tests: %d checks, %d failures\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
