/**
 * Where later cards plug into the Glass shell.
 *
 * SPEC-006 made Glass the main view and removed lumen's tabs that the mockups do not
 * have. The lumen logic below is kept as it is; each later card restyles one entry into
 * its own folder (web/src/<area>/) and swaps the import here and in app/Shell.tsx.
 *
 *   SPEC-007  lighting desk         app/DeskSlot.tsx            -> web/src/desk/
 *   SPEC-008  add a light           app/AddLight.tsx            -> web/src/addlight/
 *   SPEC-010  looks with their fade glass/LookCards.tsx reads lumen scenes until looks exist
 *   SPEC-011  groups                groups/Groups.tsx          (done)
 *   SPEC-012  effects               tabs/EffectsTab.tsx         -> web/src/effects/
 *   SPEC-013  schedules             tabs/ScheduleTab.tsx        -> web/src/schedules/
 *   SPEC-015  phone access          the phone surface is the bare URL (app/surface.ts)
 */

export { DeskSlot } from './DeskSlot'
export { AddLight } from './AddLight'
export { Groups } from '../groups/Groups'
export { EffectsTab as Effects } from '../tabs/EffectsTab'
export { ScheduleTab as Schedules } from '../tabs/ScheduleTab'
