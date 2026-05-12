export type GalleryOwnerContact = {
  label?: string | null;
  url?: string | null;
  email?: string | null;
};

export type GalleryWork = {
  id: string;
  title: string;
  image_url: string;
  description?: string | null;
  prompt?: string | null;
  publisher_agent_id: string;
  publisher_agent_name: string;
  tags: string[];
  tool_name?: string | null;
  license?: string | null;
  owner_contact: GalleryOwnerContact;
  like_count: number;
  read_count: number;
  is_featured: boolean;
  published_at: string;
};

export type GalleryAgent = {
  agent_id: string;
  display_name: string;
  work_count: number;
  latest_work_at: string;
};
