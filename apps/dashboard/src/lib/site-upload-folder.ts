/**
 * Local folder hints for final rasters from common photogrammetry exports.
 * This module reads relative paths and filenames only. The usual GeoTIFF
 * preflight and Core inspection remain responsible for accepting a file.
 */

export type UploadFolderProducer = "DJI Terra" | "PIX4Dmapper";

export type UploadFolderGroup = {
  /** Stable within this selected folder set. */
  key: string;
  /** Local folder and project hint shown to the operator. */
  label: string;
  producer: UploadFolderProducer;
  ortho: File[];
  dsm: File[];
};

export type UploadFolderRecognition = { groups: UploadFolderGroup[] };

function pathSegments(file: File): string[] | null {
  const path = file.webkitRelativePath;
  if (!path) return null;
  const segments = path.replaceAll("\\", "/").split("/").filter(Boolean);
  if (segments.length < 2 || segments.some((segment) => segment.startsWith("."))) return null;
  if (segments.some((segment) => /^(?:temp|temporary|tmp|cache|\.cache|_temp)$/i.test(segment))) return null;
  return segments;
}

function groupKey(producer: UploadFolderProducer, identity: string): string {
  return `${producer.toLowerCase().replaceAll(" ", "-")}:${identity}`;
}

function pix4dLabel(folders: readonly string[], project: string): string {
  const folderPath = folders.join(" / ");
  if (!folderPath) return project;
  return folders.at(-1) === project ? folderPath : `${folderPath} · ${project}`;
}

function addFile(
  groups: Map<string, UploadFolderGroup>,
  file: File,
  key: string,
  label: string,
  producer: UploadFolderProducer,
  kind: "ortho" | "dsm",
): void {
  let group = groups.get(key);
  if (!group) {
    group = { key, label, producer, ortho: [], dsm: [] };
    groups.set(key, group);
  }
  group[kind].push(file);
}

function pix4dMosaicProject(name: string): string | null {
  const transparent = /^(.+)_transparent_mosaic_(.+)$/i.exec(name);
  const mosaic = transparent ?? /^(.+)_mosaic_(.+)$/i.exec(name);
  if (!mosaic) return null;

  const group = mosaic[2]!;
  const normalizedGroup = group.toLowerCase().replace(/[\s-]+/g, "_");
  if (/^(?:r|red|g|green|b|blue|nir|nir\d+|rededge\d*|red_edge\d*|re\d+|ndvi|ndre|gndvi|vari|evi|savi|msavi|osavi|index|index_map|idx(?:_.*)?)$/i.test(normalizedGroup)) {
    return null;
  }
  return mosaic[1]!;
}

function collectPix4D(groups: Map<string, UploadFolderGroup>, file: File, segments: readonly string[]): void {
  if (segments.length < 3) return;
  const filename = segments.at(-1)!;
  if (!/\.tiff?$/i.test(filename)) return;
  const outputIndex = segments.length - 2;
  if (segments[outputIndex - 1]?.toLowerCase() !== "3_dsm_ortho") return;
  const outputKind = segments[outputIndex]!.toLowerCase();
  const basename = filename.replace(/\.tiff?$/i, "");
  const tileSuffix = /_-?\d+_-?\d+$/;
  if (tileSuffix.test(basename)) return;

  let kind: "ortho" | "dsm";
  let project: string;
  if (outputKind === "1_dsm") {
    const match = /^(.+)_dsm$/i.exec(basename);
    if (!match) return;
    kind = "dsm";
    project = match[1]!;
  } else if (outputKind === "2_mosaic") {
    const match = pix4dMosaicProject(basename);
    if (!match) return;
    kind = "ortho";
    project = match;
  } else {
    return;
  }

  const projectRoot = segments.slice(0, outputIndex - 1);
  const outputRoot = segments.slice(0, outputIndex).join("/");
  const key = groupKey("PIX4Dmapper", `${outputRoot}/${project}`);
  addFile(groups, file, key, pix4dLabel(projectRoot, project), "PIX4Dmapper", kind);
}

function isDjiMapPath(folders: readonly string[]): boolean {
  return folders.some((name) => /^dji[ _-]+terra$/i.test(name))
    || (folders.at(-3)?.toLowerCase() === "terra" && /^(?:default|lu)$/i.test(folders.at(-2) ?? ""));
}

/** Recognize high-confidence final outputs within an opt-in directory selection. */
export function recognizeUploadFolder(files: ArrayLike<File>): UploadFolderRecognition {
  const groups = new Map<string, UploadFolderGroup>();
  const djiFolders = new Map<string, {
    folders: string[];
    ortho: File[];
    dsm: File[];
    terraPath: boolean;
    gsddsm: boolean;
    dsmTiles: boolean;
  }>();

  for (let index = 0; index < files.length; index += 1) {
    const file = files[index];
    if (!file || !/\.tiff?$/i.test(file.name)) continue;
    const segments = pathSegments(file);
    if (!segments) continue;

    collectPix4D(groups, file, segments);

    const dsmTilesIndex = segments.findIndex((segment, segmentIndex) =>
      segment.toLowerCase() === "dsm_tiles" && segments[segmentIndex - 1]?.toLowerCase() === "map",
    );
    if (dsmTilesIndex >= 0) {
      const mapPath = segments.slice(0, dsmTilesIndex).join("/");
      const entry = djiFolders.get(mapPath) ?? {
        folders: segments.slice(0, dsmTilesIndex), ortho: [], dsm: [], terraPath: false, gsddsm: false, dsmTiles: false,
      };
      entry.dsmTiles = true;
      djiFolders.set(mapPath, entry);
      continue;
    }

    const mapIndex = segments.length - 2;
    if (segments[mapIndex]!.toLowerCase() !== "map") {
      continue;
    }

    const identity = segments.slice(0, mapIndex + 1).join("/");
    const entry = djiFolders.get(identity) ?? {
      folders: segments.slice(0, mapIndex + 1), ortho: [], dsm: [], terraPath: false, gsddsm: false, dsmTiles: false,
    };
    entry.terraPath ||= isDjiMapPath(entry.folders);
    const name = segments.at(-1)!.toLowerCase();
    if (name === "gsddsm.tif" || name === "gsddsm.tiff") entry.gsddsm = true;
    if (name === "result.tif" || name === "result.tiff") entry.ortho.push(file);
    if (name === "dsm.tif" || name === "dsm.tiff") entry.dsm.push(file);
    djiFolders.set(identity, entry);
  }

  for (const [identity, entry] of djiFolders) {
    if (entry.ortho.length === 0 && entry.dsm.length === 0) continue;
    const hasPair = entry.ortho.length > 0 && entry.dsm.length > 0;
    if (!hasPair && !entry.terraPath && !entry.gsddsm && !entry.dsmTiles) continue;
    const key = groupKey("DJI Terra", identity);
    groups.set(key, {
      key,
      label: entry.folders.join(" / "),
      producer: "DJI Terra",
      ortho: entry.ortho,
      dsm: entry.dsm,
    });
  }

  return { groups: [...groups.values()] };
}
