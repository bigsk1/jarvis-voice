/** Display-only identity. The Intelligence Profile Card is managed separately. */
class ProfileAppearance {
  constructor() {
    this.name = document.getElementById('profileDisplayName');
    this.image = document.getElementById('profileAvatar');
    this.label = document.getElementById('profileDisplayLabel');
    this.fileInput = document.getElementById('profileAvatarFile');
    this.upload = document.getElementById('uploadProfileAvatar');
    this.remove = document.getElementById('removeProfileAvatar');
    this.saveButton = document.getElementById('saveProfileAppearance');
    this.status = document.getElementById('profileAppearanceStatus');
    this.defaultImage = this.image.getAttribute('src');
    this.saved = null;
    this.file = null;
    this.removeAvatar = false;
    this.previewUrl = null;
    this.dirty = false;
    this.saving = false;
    this.requestId = 0;
    this.name.addEventListener('input', () => {
      this.dirty = true;
      this.status.textContent = 'Unsaved changes';
      this.render();
    });
    this.upload.addEventListener('click', () => this.fileInput.click());
    this.fileInput.addEventListener('change', () => this.selectFile(this.fileInput.files[0]));
    this.remove.addEventListener('click', () => {
      this.releasePreview();
      this.file = null;
      this.removeAvatar = true;
      this.dirty = true;
      this.status.textContent = 'Unsaved changes';
      this.render();
    });
    this.saveButton.addEventListener('click', () => this.save());
    document.getElementById('retryProfileAppearance').addEventListener('click', () => this.load());
    this.render();
  }

  releasePreview() {
    if (this.previewUrl) URL.revokeObjectURL(this.previewUrl);
    this.previewUrl = null;
    this.fileInput.value = '';
  }

  reset() {
    if (this.saving) return;
    this.requestId++;
    this.releasePreview();
    this.file = null;
    this.removeAvatar = false;
    this.dirty = false;
    this.name.value = this.saved?.display_name || '';
    this.status.textContent = '';
    this.render();
  }

  render() {
    this.label.textContent = this.name.value.trim() || 'Administrator';
    this.image.src = this.previewUrl || (!this.removeAvatar && this.saved?.avatar) || this.defaultImage;
    const disabled = this.saving || !this.saved;
    this.name.disabled = disabled;
    this.upload.disabled = disabled;
    this.remove.disabled = disabled || (!this.previewUrl && (!this.saved?.avatar || this.removeAvatar));
    this.saveButton.disabled = disabled || !this.dirty;
    this.saveButton.textContent = this.saving ? 'Saving…' : 'Save appearance';
  }

  async load() {
    if (this.dirty || this.saving) return;
    const id = ++this.requestId;
    this.status.textContent = 'Loading appearance…';
    const retry = document.getElementById('retryProfileAppearance');
    retry.hidden = true;
    try {
      const response = await fetch('/api/profile-appearance', {cache: 'no-store'});
      const data = await response.json();
      if (!response.ok || !data.ok || !data.profile) throw new Error(data.error || 'Could not load your appearance.');
      if (id !== this.requestId || this.dirty || this.saving) return;
      this.saved = data.profile;
      this.reset();
    } catch (error) {
      if (id !== this.requestId || this.dirty || this.saving) return;
      this.status.textContent = error.message || 'Could not load your appearance.';
      retry.hidden = false;
    }
  }

  selectFile(file) {
    if (!file || this.saving || !this.saved) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024) {
      this.fileInput.value = '';
      this.status.textContent = 'Choose a PNG, JPEG, or WebP image smaller than 5 MB.';
      return;
    }
    this.releasePreview();
    this.file = file;
    this.previewUrl = URL.createObjectURL(file);
    this.removeAvatar = false;
    this.dirty = true;
    this.status.textContent = 'Unsaved changes';
    this.render();
  }

  async save() {
    if (!this.dirty || this.saving || !this.saved) return;
    if (!this.name.reportValidity()) return;
    this.saving = true;
    this.requestId++;
    this.render();
    try {
      const form = new FormData();
      form.set('display_name', this.name.value);
      form.set('remove_avatar', String(this.removeAvatar));
      if (this.file) form.set('avatar', this.file);
      const response = await fetch('/api/profile-appearance', {method: 'PUT', body: form});
      const data = await response.json();
      if (!response.ok || !data.ok || !data.profile) throw new Error(data.error || 'Could not save your appearance.');
      this.saved = data.profile;
      this.saving = false;
      this.reset();
      this.status.textContent = 'Appearance saved. Your companion will update automatically.';
    } catch (error) {
      this.status.textContent = error.message || 'Could not save your appearance.';
    } finally {
      this.saving = false;
      this.render();
    }
  }
}

window.ProfileAppearance = ProfileAppearance;
