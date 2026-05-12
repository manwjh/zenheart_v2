import type { SiteLocale } from "@/features/locale/siteLocale";

export type LabShell = {
  sectionsAria: string;
  tabWall: string;
};

export const labShellByLocale: Record<SiteLocale, LabShell> = {
  zh: {
    sectionsAria: "实验室分区",
    tabWall: "Wall",
  },
  en: {
    sectionsAria: "Lab sections",
    tabWall: "Wall",
  },
};
