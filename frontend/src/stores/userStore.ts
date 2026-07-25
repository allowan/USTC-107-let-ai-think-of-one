import { create } from 'zustand';

const LOCAL_USER = {
  user_id: 'local_user',
  username: 'local_user',
  is_admin: true,
};

interface UserState {
  user: typeof LOCAL_USER | null;
  ready: boolean;
}

export const useUserStore = create<UserState>(() => ({
  user: LOCAL_USER,
  ready: true,
}));
