/**
 * Where later cards plug into the Glass shell.
 *
 * SPEC-006 made Glass the main view and removed lumen's tabs that the mockups do not
 * have. The lumen logic below is kept as it is; each later card restyles one entry into
 * its own folder (web/src/<area>/) and swaps the import here and in app/Shell.tsx.
 *
 *   SPEC-007  lighting desk         done: web/src/desk/
 *   SPEC-008  add a light           done: web/src/add/
 *   SPEC-010  looks with their fade glass/LookCards.tsx reads lumen scenes until looks exist
 *   SPEC-011  groups                tabs/mesh/Groups.tsx        -> web/src/groups/
 *   SPEC-012  effects               tabs/EffectsTab.tsx         -> web/src/effects/
 *   SPEC-013  schedules             tabs/ScheduleTab.tsx        -> web/src/schedules/
 *   SPEC-015  phone access          the phone surface is the bare URL (app/surface.ts)
 */

export { Desk as DeskSlot } from '../desk/Desk'
export { AddLight } from '../add/AddLight'
export { Groups } from '../tabs/mesh/Groups'
export { EffectsTab as Effects } from '../tabs/EffectsTab'
export { ScheduleTab as Schedules } from '../tabs/ScheduleTab'
