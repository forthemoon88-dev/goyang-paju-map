-- ================================================
-- 고양·파주 도시계획 지도 - Supabase 초기화 SQL
-- Supabase > SQL Editor에서 실행하세요
-- ================================================

-- 1. 사용자 프로필 테이블 (역할 관리)
CREATE TABLE IF NOT EXISTS profiles (
  id UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
  email TEXT NOT NULL,
  name TEXT,
  role TEXT NOT NULL DEFAULT 'pending',  -- pending / uploader / admin
  created_at TIMESTAMPTZ DEFAULT NOW(),
  approved_at TIMESTAMPTZ
);

-- 2. KMZ 업로드 파일 테이블
CREATE TABLE IF NOT EXISTS kmz_uploads (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  uploader_id UUID REFERENCES profiles(id) ON DELETE SET NULL,
  file_name TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  label TEXT NOT NULL,           -- 지도에 표시될 이름
  color TEXT DEFAULT '#60a5fa',  -- 레이어 색상
  layer_type TEXT DEFAULT 'other', -- road/dev/env/other
  description TEXT,
  status TEXT DEFAULT 'pending', -- pending / approved / rejected
  reviewed_by UUID REFERENCES profiles(id),
  reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. 승인된 레이어 테이블 (지도에 표시되는 것)
CREATE TABLE IF NOT EXISTS layers (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  kmz_upload_id UUID REFERENCES kmz_uploads(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  color TEXT DEFAULT '#60a5fa',
  layer_type TEXT DEFAULT 'other',
  visible BOOLEAN DEFAULT TRUE,
  sort_order INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ================================================
-- Row Level Security (RLS) 활성화
-- ================================================

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE kmz_uploads ENABLE ROW LEVEL SECURITY;
ALTER TABLE layers ENABLE ROW LEVEL SECURITY;

-- ================================================
-- profiles 정책
-- ================================================

-- 본인 프로필 읽기
CREATE POLICY "본인 프로필 읽기" ON profiles
  FOR SELECT USING (auth.uid() = id);

-- 관리자는 모든 프로필 읽기
CREATE POLICY "관리자 프로필 전체 읽기" ON profiles
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
  );

-- 관리자는 프로필 수정 (역할 변경)
CREATE POLICY "관리자 프로필 수정" ON profiles
  FOR UPDATE USING (
    EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
  );

-- 회원가입 시 프로필 자동 생성
CREATE POLICY "프로필 생성" ON profiles
  FOR INSERT WITH CHECK (auth.uid() = id);

-- ================================================
-- kmz_uploads 정책
-- ================================================

-- 본인 업로드 읽기
CREATE POLICY "본인 업로드 읽기" ON kmz_uploads
  FOR SELECT USING (uploader_id = auth.uid());

-- 관리자 전체 읽기
CREATE POLICY "관리자 업로드 전체 읽기" ON kmz_uploads
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
  );

-- uploader/admin만 파일 업로드
CREATE POLICY "승인된 사용자 업로드" ON kmz_uploads
  FOR INSERT WITH CHECK (
    EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role IN ('uploader','admin'))
  );

-- 관리자만 상태 변경
CREATE POLICY "관리자 업로드 수정" ON kmz_uploads
  FOR UPDATE USING (
    EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
  );

-- ================================================
-- layers 정책 (누구나 읽기 가능 - 지도 표시용)
-- ================================================

CREATE POLICY "레이어 전체 공개" ON layers
  FOR SELECT USING (TRUE);

CREATE POLICY "관리자 레이어 관리" ON layers
  FOR ALL USING (
    EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
  );

-- ================================================
-- Storage 버킷 생성 (SQL Editor에서 실행)
-- ================================================

INSERT INTO storage.buckets (id, name, public)
VALUES ('kmz-files', 'kmz-files', false)
ON CONFLICT DO NOTHING;

-- Storage 정책: 승인된 사용자만 업로드
CREATE POLICY "승인된 사용자 KMZ 업로드" ON storage.objects
  FOR INSERT WITH CHECK (
    bucket_id = 'kmz-files' AND
    EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role IN ('uploader','admin'))
  );

-- 본인 파일 읽기 + 관리자 전체 읽기
CREATE POLICY "KMZ 파일 읽기" ON storage.objects
  FOR SELECT USING (
    bucket_id = 'kmz-files' AND (
      auth.uid()::text = (storage.foldername(name))[1] OR
      EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin')
    )
  );

-- ================================================
-- 회원가입 시 프로필 자동 생성 트리거
-- ================================================

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, email, name, role)
  VALUES (
    NEW.id,
    NEW.email,
    COALESCE(NEW.raw_user_meta_data->>'name', split_part(NEW.email, '@', 1)),
    'pending'
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ================================================
-- 관리자 계정 설정 (본인 이메일로 변경 후 실행)
-- ================================================
-- 아래 이메일을 본인 관리자 이메일로 바꿔서 실행하세요
-- UPDATE profiles SET role = 'admin' WHERE email = 'forthemoon88@gmail.com';
