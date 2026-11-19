import { describe, expect, it } from "vitest";

import { recognizeUploadFolder } from "@/lib/site-upload-folder";

function localFile(relativePath: string): File {
  const name = relativePath.split("/").at(-1)!;
  return Object.defineProperty(new File([new Uint8Array([1])], name), "webkitRelativePath", { value: relativePath }) as File;
}

describe("recognizeUploadFolder", () => {
  it("recognizes only the paired primary rasters in a DJI Terra map folder", () => {
    const result = recognizeUploadFolder([
      localFile("survey/terra/default/map/result.tif"),
      localFile("survey/terra/default/map/dsm.tif"),
      localFile("survey/terra/default/map/gsddsm.tif"),
      localFile("survey/terra/default/map/result_Red.tif"),
      localFile("survey/terra/default/map/index_map/result.tif"),
      localFile("survey/terra/default/map/result_tiles/tile_0.tif"),
      localFile("survey/terra/default/map/.temp/dsm.tif"),
    ]);

    expect(result.groups).toHaveLength(1);
    expect(result.groups[0]).toMatchObject({ producer: "DJI Terra" });
    expect(result.groups[0]!.ortho.map((file) => file.name)).toEqual(["result.tif"]);
    expect(result.groups[0]!.dsm.map((file) => file.name)).toEqual(["dsm.tif"]);
  });

  it("does not infer Terra from an unpaired generic map filename", () => {
    expect(recognizeUploadFolder([localFile("unrelated/map/result.tif")]).groups).toEqual([]);
    expect(recognizeUploadFolder([localFile("unrelated/map/dsm.tif")]).groups).toEqual([]);
    expect(recognizeUploadFolder([localFile("research/terra/unrelated/map/result.tif")]).groups).toEqual([]);
  });

  it("recognizes a sole primary raster with DJI path or sibling corroboration", () => {
    const byPath = recognizeUploadFolder([localFile("DJI Terra/default/map/result.tif")]);
    const bySibling = recognizeUploadFolder([
      localFile("unrelated/map/dsm.tif"),
      localFile("unrelated/map/gsddsm.tif"),
    ]);
    const byTiles = recognizeUploadFolder([
      localFile("unrelated/map/result.tif"),
      localFile("unrelated/map/dsm_tiles/0/0/tile.tif"),
    ]);

    expect(byPath.groups[0]!.ortho.map((file) => file.name)).toEqual(["result.tif"]);
    expect(bySibling.groups[0]!.dsm.map((file) => file.name)).toEqual(["dsm.tif"]);
    expect(byTiles.groups[0]!.ortho.map((file) => file.name)).toEqual(["result.tif"]);
  });

  it("keeps identical DJI map suffixes from different survey dates separate", () => {
    const result = recognizeUploadFolder([
      localFile("campaign/05.07.2024/terra/default/map/result.tif"),
      localFile("campaign/05.07.2024/terra/default/map/dsm.tif"),
      localFile("campaign/05.07.2025/terra/default/map/result.tif"),
      localFile("campaign/05.07.2025/terra/default/map/dsm.tif"),
    ]);

    expect(result.groups).toHaveLength(2);
    expect(new Set(result.groups.map((group) => group.key)).size).toBe(2);
    expect(new Set(result.groups.map((group) => group.label)).size).toBe(2);
  });

  it("recognizes the canonical PIX4Dmapper DSM and mosaic files as one project", () => {
    const result = recognizeUploadFolder([
      localFile("survey-east/3_dsm_ortho/1_dsm/survey-east_dsm.tif"),
      localFile("survey-east/3_dsm_ortho/2_mosaic/survey-east_transparent_mosaic_group1.tif"),
      localFile("survey-east/3_dsm_ortho/2_mosaic/survey-east_mosaic_group2.tif"),
      localFile("survey-east/3_dsm_ortho/2_mosaic/tiles/survey-east_transparent_mosaic_group1_0_0.tif"),
      localFile("survey-east/3_dsm_ortho/extras/dtm/survey-east_dtm.tif"),
    ]);

    expect(result.groups).toHaveLength(1);
    expect(result.groups[0]).toMatchObject({ producer: "PIX4Dmapper" });
    expect(result.groups[0]!.dsm.map((file) => file.name)).toEqual(["survey-east_dsm.tif"]);
    expect(result.groups[0]!.ortho.map((file) => file.name)).toEqual([
      "survey-east_transparent_mosaic_group1.tif",
      "survey-east_mosaic_group2.tif",
    ]);
  });

  it("keeps custom mosaic groups and excludes bands, indices, and coordinate tile suffixes", () => {
    const result = recognizeUploadFolder([
      localFile("capture-cache/3_dsm_ortho/2_mosaic/capture-cache_mosaic_RGB.tif"),
      localFile("capture-cache/3_dsm_ortho/2_mosaic/capture-cache_transparent_mosaic_main-field.tiff"),
      localFile("capture-cache/3_dsm_ortho/2_mosaic/capture-cache_mosaic_NIR.tif"),
      localFile("capture-cache/3_dsm_ortho/2_mosaic/capture-cache_mosaic_NDVI.tif"),
      localFile("capture-cache/3_dsm_ortho/2_mosaic/capture-cache_mosaic_red.tif"),
      localFile("capture-cache/3_dsm_ortho/2_mosaic/capture-cache_mosaic_custom_12_4.tif"),
      localFile("capture-cache/3_dsm_ortho/2_mosaic/tiles/capture-cache_mosaic_group1.tif"),
      localFile("capture-cache/3_dsm_ortho/1_dsm/capture-cache_dsm_12_4.tif"),
      localFile("capture-cache/3_dsm_ortho/1_dsm/capture-cache_dsm.tif"),
    ]);

    expect(result.groups).toHaveLength(1);
    expect(result.groups[0]!.label).toBe("capture-cache");
    expect(result.groups[0]!.ortho.map((file) => file.name)).toEqual([
      "capture-cache_mosaic_RGB.tif",
      "capture-cache_transparent_mosaic_main-field.tiff",
    ]);
    expect(result.groups[0]!.dsm.map((file) => file.name)).toEqual(["capture-cache_dsm.tif"]);
  });

  it("keeps different project names and output roots in separate groups", () => {
    const result = recognizeUploadFolder([
      localFile("batch/3_dsm_ortho/1_dsm/north_dsm.tif"),
      localFile("batch/3_dsm_ortho/2_mosaic/south_mosaic_group1.tif"),
      localFile("other-batch/3_dsm_ortho/1_dsm/north_dsm.tif"),
    ]);

    expect(result.groups).toHaveLength(3);
    expect(result.groups.every((group) => group.ortho.length === 0 || group.dsm.length === 0)).toBe(true);
    expect(new Set(result.groups.map((group) => group.key)).size).toBe(3);
  });

  it("preserves case-distinct project paths as separate identities", () => {
    const result = recognizeUploadFolder([
      localFile("campaign/05.07.2024/3_dsm_ortho/1_dsm/Survey_dsm.tif"),
      localFile("campaign/05.07.2024/3_dsm_ortho/2_mosaic/Survey_mosaic_group1.tif"),
      localFile("campaign/05.07.2024/3_dsm_ortho/1_dsm/survey_dsm.tif"),
      localFile("campaign/05.07.2024/3_dsm_ortho/2_mosaic/survey_mosaic_group1.tif"),
    ]);

    expect(result.groups).toHaveLength(2);
    expect(new Set(result.groups.map((group) => group.key)).size).toBe(2);
    expect(result.groups.every((group) => group.ortho.length === 1 && group.dsm.length === 1)).toBe(true);
  });

  it("works when the selected folder begins at 3_dsm_ortho", () => {
    const result = recognizeUploadFolder([
      localFile("3_dsm_ortho/1_dsm/site_dsm.tif"),
      localFile("3_dsm_ortho/2_mosaic/site_mosaic_group1.tif"),
    ]);

    expect(result.groups).toHaveLength(1);
    expect(result.groups[0]!.dsm).toHaveLength(1);
    expect(result.groups[0]!.ortho).toHaveLength(1);
  });
});
