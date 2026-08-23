import { apiDelete, apiGet, apiPut } from "./client";

export interface FaceTemplateSummary {
  personId: string;
  personName: string;
  modelVersion: string;
  modelHash: string;
  pipelineVersion: number;
  revision: number;
  createdAt: string;
  updatedAt: string;
}

export interface FaceTemplateLibrary {
  capacity: number;
  count: number;
  templates: FaceTemplateSummary[];
}

export interface FaceSeatAssignment {
  seatId: number;
  personId: string | null;
  attendeeId: number | null;
  personName: string | null;
  templateRevision: number | null;
}

export interface FaceSeatAssignments {
  meetingId: number;
  templateSetRevision: number;
  assignments: FaceSeatAssignment[];
}

export interface TabletFaceSyncStatus {
  seat_id: number;
  online: boolean;
  app_version: string | null;
  face_template_meeting_id: number | null;
  face_template_set_revision: number | null;
  face_template_sync_count: number | null;
  face_template_sync_status: string | null;
  face_template_sync_error: string | null;
}

interface HardwareStatus {
  tablets: TabletFaceSyncStatus[];
}

function auth(token: string): HeadersInit {
  return { "X-SmartDesk-Device-Token": token };
}

export function fetchFaceTemplateLibrary(
  deviceId: string,
  token: string,
): Promise<FaceTemplateLibrary> {
  return apiGet<FaceTemplateLibrary>(
    `/face-templates?deviceId=${encodeURIComponent(deviceId)}`,
    auth(token),
  );
}

export function deleteFaceTemplate(
  personId: string,
  deviceId: string,
  token: string,
): Promise<void> {
  return apiDelete<void>(
    `/face-templates/${encodeURIComponent(personId)}?deviceId=${encodeURIComponent(deviceId)}`,
    auth(token),
  );
}

export function fetchFaceAssignments(
  meetingId: number,
  deviceId: string,
  token: string,
): Promise<FaceSeatAssignments> {
  return apiGet<FaceSeatAssignments>(
    `/face-templates/meetings/${meetingId}/assignments?deviceId=${encodeURIComponent(deviceId)}`,
    auth(token),
  );
}

export function updateFaceAssignments(
  meetingId: number,
  deviceId: string,
  token: string,
  assignments: Array<{ seatId: number; personId: string | null }>,
): Promise<FaceSeatAssignments> {
  return apiPut<FaceSeatAssignments>(
    `/face-templates/meetings/${meetingId}/assignments`,
    { deviceId, assignments },
    auth(token),
  );
}

export async function fetchTabletFaceSyncStatus(): Promise<TabletFaceSyncStatus[]> {
  const status = await apiGet<HardwareStatus>("/hardware/status");
  return status.tablets.filter((tablet) => tablet.seat_id >= 2 && tablet.seat_id <= 9);
}
