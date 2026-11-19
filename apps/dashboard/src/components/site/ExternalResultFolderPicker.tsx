"use client";

import { useId, useRef, useState } from "react";

import type { ArtifactSlot } from "@/lib/geo/geotiff-header";
import { recognizeUploadFolder, type UploadFolderGroup } from "@/lib/site-upload-folder";

const slots = ["ortho", "dsm"] as const;
const labels = { ortho: "정사영상", dsm: "DSM" };
export type FolderUploadFile = { file: File; kind: ArtifactSlot };

export function ExternalResultFolderPicker({ disabled, onSelect }: {
  disabled: boolean;
  onSelect: (items: FolderUploadFile[], folderLabel: string) => void | Promise<void>;
}) {
  const input = useRef<HTMLInputElement>(null);
  const groupName = useId();
  const [groups, setGroups] = useState<UploadFolderGroup[]>([]);
  const [groupKey, setGroupKey] = useState("");
  const [choices, setChoices] = useState({ ortho: "", dsm: "" });
  const [notice, setNotice] = useState("");
  const group = groups.find((item) => item.key === groupKey);
  const selectGroup = (key: string) => {
    setGroupKey(key);
    setChoices({ ortho: "", dsm: "" });
  };

  const clear = () => {
    setGroups([]);
    setGroupKey("");
    setChoices({ ortho: "", dsm: "" });
    setNotice("");
  };

  const choose = (selection: UploadFolderGroup, files: FolderUploadFile[]) => {
    clear();
    void onSelect(files, `${selection.producer} 형식 · ${selection.label}`);
  };

  const scan = (files: FileList) => {
    clear();
    const found = recognizeUploadFolder(files).groups;
    if (found.length === 0) {
      setNotice("정사영상이나 DSM을 찾지 못했습니다. DJI Terra의 map 또는 PIX4Dmapper의 3_dsm_ortho 폴더를 고르거나 GeoTIFF 파일을 직접 선택하세요.");
      return;
    }
    const only = found[0]!;
    if (found.length === 1 && slots.every((kind) => only[kind].length <= 1)) {
      choose(only, slots.flatMap((kind) => only[kind].map((file) => ({ file, kind }))));
      return;
    }
    setGroups(found);
    if (found.length === 1) setGroupKey(only.key);
  };

  const selected = group ? slots.flatMap((kind) => {
    const options = group[kind];
    const file = options.length === 1 ? options[0] : options.find((_, index) => String(index) === choices[kind]);
    return file ? [{ file, kind }] : [];
  }) : [];
  const ready = group && selected.length > 0 && slots.every((kind) => group[kind].length <= 1 || choices[kind] !== "");

  return <>
    <button type="button" className="btn w-fit" disabled={disabled} onClick={() => {
      if (input.current && "webkitdirectory" in input.current) input.current.click();
      else setNotice("이 브라우저에서는 폴더를 열 수 없습니다. GeoTIFF 파일을 직접 선택하세요.");
    }}>결과 폴더 고르기</button>
    <input type="file" ref={input} {...{ webkitdirectory: "" }} multiple hidden aria-label="결과 폴더 선택" disabled={disabled}
      onChange={(event) => {
        if (!disabled && event.currentTarget.files) scan(event.currentTarget.files);
        event.currentTarget.value = "";
      }} />
    {notice && <p role="status" className="basis-full text-caption leading-5 text-ink-2">{notice}</p>}
    {groups.length > 0 && <fieldset disabled={disabled} className="flex min-w-0 basis-full flex-col gap-2 rounded-lg border border-line bg-surface px-3 py-3 text-left">
      <legend className="px-1 text-caption font-semibold">등록할 결과 선택</legend>
      {groups.length > 1 && groups.length <= 4 ? <div role="radiogroup" aria-label="결과 폴더" className="grid gap-1.5">
        {groups.map((item) => <label key={item.key} className={`flex min-w-0 cursor-pointer items-start gap-2 rounded-md border px-2.5 py-2 ${item.key === groupKey ? "border-ink-1 bg-sunk" : "border-line"}`}>
          <input type="radio" name={groupName} value={item.key} checked={groupKey === item.key}
            className="mt-1 shrink-0 accent-ink-1" onChange={() => selectGroup(item.key)} />
          <span className="min-w-0">
            <span className="block break-words text-body font-semibold [overflow-wrap:anywhere]">{item.label}</span>
            <span className="text-caption text-ink-muted">{item.producer} 형식 · {slots.filter((kind) => item[kind].length > 0).map((kind) => labels[kind]).join(" · ")}</span>
          </span>
        </label>)}
      </div> : groups.length > 1 ? <label className="flex min-w-0 flex-col gap-1 text-caption">
        결과 폴더
        <select className="input w-full min-w-0" value={groupKey} onChange={(event) => selectGroup(event.target.value)}>
          <option value="">결과 폴더 {groups.length}개 중 선택</option>
          {groups.map((item) => <option key={item.key} value={item.key}>{item.producer} 형식 · {item.label}</option>)}
        </select>
      </label> : <p className="break-all text-caption text-ink-2">{group?.producer} 형식 · {group?.label}</p>}
      {group && slots.map((kind) => {
        const files = group[kind];
        if (files.length < 2) return files[0] ? <p key={kind} className="break-all text-caption">{labels[kind]} · {files[0].name}</p> : null;
        return <label key={kind} className="flex min-w-0 flex-col gap-1 text-caption">
          {labels[kind]} 파일
          <select className="input w-full min-w-0" value={choices[kind]} onChange={(event) => setChoices({ ...choices, [kind]: event.target.value })}>
            <option value="">파일 {files.length}개 중 선택</option>
            {files.map((file, index) => <option key={index} value={String(index)}>{file.name}</option>)}
            <option value="skip">이번 등록에서 제외</option>
          </select>
        </label>;
      })}
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn" disabled={!ready} onClick={() => { if (group && ready) choose(group, selected); }}>선택한 파일 사용</button>
        <button type="button" className="tap-target px-2 text-caption text-ink-2 underline" onClick={clear}>취소</button>
      </div>
    </fieldset>}
  </>;
}
