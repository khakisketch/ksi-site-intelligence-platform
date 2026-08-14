#include "psdk_tap/ndjson_writer.h"

#include <inttypes.h>
#include <stdlib.h>

static void write_json_escaped_string(FILE *file, const char *value)
{
    fputc('"', file);
    for (const unsigned char *p = (const unsigned char *) value; *p != '\0'; ++p) {
        unsigned char c = *p;
        switch (c) {
            case '"':
                fputs("\\\"", file);
                break;
            case '\\':
                fputs("\\\\", file);
                break;
            case '\n':
                fputs("\\n", file);
                break;
            case '\r':
                fputs("\\r", file);
                break;
            case '\t':
                fputs("\\t", file);
                break;
            default:
                if (c < 0x20) {
                    fprintf(file, "\\u%04x", c);
                } else {
                    fputc((int) c, file);
                }
                break;
        }
    }
    fputc('"', file);
}

bool ksi_ndjson_open(ksi_ndjson_writer_t *writer, const char *out_path)
{
    writer->file = fopen(out_path, "w");
    if (writer->file == NULL) {
        return false;
    }
    if (pthread_mutex_init(&writer->mutex, NULL) != 0) {
        fclose(writer->file);
        writer->file = NULL;
        return false;
    }
    /* 라인버퍼링 — 프로세스가 중간에 죽어도(예: --duration-sec 초과 후 강제종료 경로버그)
     * 이미 쓴 줄까지는 디스크에 남는다. */
    setvbuf(writer->file, NULL, _IOLBF, 0);
    return true;
}

void ksi_ndjson_close(ksi_ndjson_writer_t *writer)
{
    if (writer->file != NULL) {
        fflush(writer->file);
        fclose(writer->file);
        writer->file = NULL;
    }
    pthread_mutex_destroy(&writer->mutex);
}

void ksi_ndjson_write_meta(ksi_ndjson_writer_t *writer,
                            int tap_version,
                            const char *psdk_version,
                            const char *started_at_utc,
                            const char *aircraft_sn,
                            int64_t anchor_mono_ns,
                            const char *anchor_wall_utc,
                            bool capability_frame_sensor_ts,
                            bool capability_telemetry_sensor_ts,
                            const char *frame_source,
                            const char *frame_timestamp_provenance,
                            const char *sensor_us_domain)
{
    pthread_mutex_lock(&writer->mutex);
    fprintf(writer->file, "{\"type\":\"meta\",\"tap_version\":%d,\"psdk_version\":", tap_version);
    write_json_escaped_string(writer->file, psdk_version);
    fprintf(writer->file, ",\"started_at_utc\":");
    write_json_escaped_string(writer->file, started_at_utc);
    fprintf(writer->file, ",\"aircraft_sn\":");
    if (aircraft_sn != NULL) {
        write_json_escaped_string(writer->file, aircraft_sn);
    } else {
        fputs("null", writer->file);
    }
    fprintf(writer->file, ",\"clock\":{\"mono_ns\":%" PRId64 ",\"wall_utc\":", anchor_mono_ns);
    write_json_escaped_string(writer->file, anchor_wall_utc);
    fprintf(writer->file,
            "},\"capabilities\":{\"frame_sensor_ts\":%s,\"telemetry_sensor_ts\":%s}",
            capability_frame_sensor_ts ? "true" : "false",
            capability_telemetry_sensor_ts ? "true" : "false");
    fprintf(writer->file, ",\"frame_source\":");
    write_json_escaped_string(writer->file, frame_source);
    fprintf(writer->file, ",\"frame_timestamp_provenance\":");
    write_json_escaped_string(writer->file, frame_timestamp_provenance);
    fprintf(writer->file, ",\"timestamp_contract\":{\"sensor_us_domain\":");
    write_json_escaped_string(writer->file, sensor_us_domain);
    fputs("}}\n", writer->file);
    fflush(writer->file);
    pthread_mutex_unlock(&writer->mutex);
}

static void write_endpoint(FILE *file, ksi_ndjson_endpoint_t endpoint)
{
    fprintf(file, "{\"recv_mono_ns\":%" PRId64 ",\"sensor_us\":", endpoint.recv_mono_ns);
    if (endpoint.has_sensor_us) {
        fprintf(file, "%" PRId64, endpoint.sensor_us);
    } else {
        fputs("null", file);
    }
    fputs(",\"sensor_timestamp_raw_u64\":", file);
    if (endpoint.has_sensor_timestamp_raw_u64) {
        /* JSON number는 JavaScript에서 uint64 정밀도를 잃는다. 이 raw diagnostic
         * 값은 의도적으로 decimal string으로 기록해 아무 언어에서도 비가역 변환이
         * 일어나지 않게 한다. */
        fprintf(file, "\"%" PRIu64 "\"", endpoint.sensor_timestamp_raw_u64);
    } else {
        fputs("null", file);
    }
    if (endpoint.has_perception_metadata) {
        fprintf(file,
                ",\"perception\":{\"data_id\":%u,\"sequence\":%u,\"data_type\":%" PRIu32
                ",\"raw_index\":%" PRIu32 ",\"raw_direction\":%u,\"bpp\":%u,\"width\":%" PRIu32
                ",\"height\":%" PRIu32 ",\"buffer_len\":%" PRIu32 "}",
                (unsigned int) endpoint.perception_data_id,
                (unsigned int) endpoint.perception_sequence,
                endpoint.perception_data_type,
                endpoint.perception_raw_index,
                (unsigned int) endpoint.perception_raw_direction,
                (unsigned int) endpoint.perception_bpp,
                endpoint.perception_width,
                endpoint.perception_height,
                endpoint.perception_buffer_len);
    }
    fputc('}', file);
}

void ksi_ndjson_write_sample(ksi_ndjson_writer_t *writer,
                              int64_t sample_index,
                              ksi_ndjson_endpoint_t frame,
                              ksi_ndjson_endpoint_t telemetry,
                              bool telemetry_has_hw_flag,
                              bool telemetry_hw_flag,
                              const char *pairing_strategy,
                              int64_t gap_ns)
{
    pthread_mutex_lock(&writer->mutex);
    fprintf(writer->file, "{\"type\":\"sample\",\"i\":%" PRId64 ",\"frame\":", sample_index);
    write_endpoint(writer->file, frame);
    fprintf(writer->file, ",\"telemetry\":");
    write_endpoint(writer->file, telemetry);
    if (telemetry_has_hw_flag) {
        fprintf(writer->file, ",\"telemetry_hw_flag\":%s", telemetry_hw_flag ? "true" : "false");
    }
    fprintf(writer->file, ",\"pairing\":{\"strategy\":");
    write_json_escaped_string(writer->file, pairing_strategy);
    fprintf(writer->file, ",\"gap_ns\":%" PRId64 "}}\n", gap_ns);
    pthread_mutex_unlock(&writer->mutex);
}

void ksi_ndjson_write_stat(ksi_ndjson_writer_t *writer,
                            uint64_t frames_received,
                            uint64_t telemetry_received,
                            uint64_t samples_written,
                            uint64_t frames_dropped_no_telemetry,
                            int64_t target_num_samples,
                            const char *stop_reason,
                            bool insufficient_samples)
{
    pthread_mutex_lock(&writer->mutex);
    fprintf(writer->file,
            "{\"type\":\"stat\",\"frames_received\":%" PRIu64 ",\"telemetry_received\":%" PRIu64
            ",\"samples_written\":%" PRIu64 ",\"frames_dropped_no_telemetry\":%" PRIu64
            ",\"target_num_samples\":%" PRId64 ",\"insufficient_samples\":%s,\"stop_reason\":",
            frames_received, telemetry_received, samples_written, frames_dropped_no_telemetry,
            target_num_samples, insufficient_samples ? "true" : "false");
    write_json_escaped_string(writer->file, stop_reason);
    fputs("}\n", writer->file);
    fflush(writer->file);
    pthread_mutex_unlock(&writer->mutex);
}
