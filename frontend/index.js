async function mountSharedComponents() {
  const components = [
    ['[data-site-header]', '/components/site-header.html'],
    ['[data-site-footer]', '/components/site-footer.html'],
  ];

  await Promise.all(components.map(async ([selector, url]) => {
    const target = document.querySelector(selector);
    if (!target) return;

    try {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Could not load ${url} (${response.status})`);
      }
      target.innerHTML = await response.text();
    } catch (error) {
      console.error(error);
    }
  }));

  const currentPath = window.location.pathname.replace(/\/$/, '') || '/';
  document.querySelectorAll('.site-nav a').forEach((link) => {
    const linkPath = new URL(link.href).pathname.replace(/\/$/, '') || '/';
    if (linkPath === currentPath) link.setAttribute('aria-current', 'page');
  });
}

let requestForm;
let formStatus;
let signedOut;
let signedIn;
let accountName;
let accountEmail;
let signOutButton;
let adminLink;
let openProjectLink;
let adminPage;
let adminAccessStatus;
let adminPanel;
let adminStatus;
let adminUsers;
let workPackageList;
let workPackageStatus;
let refreshWorkPackagesButton;

async function loadAdminUsers() {
  if (!adminStatus || !adminUsers) {
    return;
  }

  adminStatus.textContent = 'Loading users...';
  adminUsers.replaceChildren();

  try {
    const response = await fetch('/api/admin/users');

    if (!response.ok) {
      throw new Error(`User list request failed (${response.status})`);
    }

    const data = await response.json();

    // Accept common list response formats without assuming one shape.
    const users = Array.isArray(data)
      ? data
      : Array.isArray(data.users)
        ? data.users
        : Array.isArray(data._embedded?.elements)
          ? data._embedded.elements
          : null;

    if (!users) {
      adminStatus.textContent = 'User list loaded; response format needs inspection.';
      const output = document.createElement('pre');
      output.textContent = JSON.stringify(data, null, 2);
      adminUsers.append(output);
      return;
    }

    adminStatus.textContent = `${users.length} user(s) found.`;

    const list = document.createElement('ul');

    for (const user of users) {
      const item = document.createElement('li');
      const name = user.name || user.email || `User ${user.id}`;
      const email = user.email || '';
      const role = user.role || 'unknown';
      const active = user.active === false || user.active === 0
        ? 'Disabled'
        : 'Active';

      item.textContent = `${name} (${email}) — ${role} — ${active}`;
      list.append(item);
    }

    adminUsers.append(list);
  } catch (error) {
    adminStatus.textContent = `Could not load users: ${error.message}`;
  }
}

function addWorkPackageTextField(form, labelText, name, value, multiline = false) {
  const label = document.createElement('label');
  label.className = 'work-package-field';
  const labelTextElement = document.createElement('span');
  labelTextElement.textContent = labelText;
  const field = document.createElement(multiline ? 'textarea' : 'input');
  field.name = name;
  field.value = value || '';
  if (!multiline) field.type = 'text';
  label.append(labelTextElement, field);
  form.append(label);
}

function addWorkPackageSelect(form, labelText, name, choices, selectedId, allowNone = false) {
  const label = document.createElement('label');
  label.className = 'work-package-field';
  const labelTextElement = document.createElement('span');
  labelTextElement.textContent = labelText;
  const select = document.createElement('select');
  select.name = name;

  if (allowNone) {
    const noneOption = document.createElement('option');
    noneOption.value = '';
    noneOption.textContent = 'Unassigned';
    select.append(noneOption);
  }

  for (const choice of choices) {
    const option = document.createElement('option');
    option.value = choice.id;
    option.textContent = choice.name;
    option.selected = String(choice.id) === String(selectedId);
    select.append(option);
  }

  label.append(labelTextElement, select);
  form.append(label);
}

function renderWorkPackage(item, options) {
  const article = document.createElement('article');
  article.className = 'work-package-item';

  const heading = document.createElement('div');
  heading.className = 'work-package-item-heading';
  const link = document.createElement('a');
  link.href = item.url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.textContent = `#${item.id} ${item.subject}`;
  heading.append(link);

  const form = document.createElement('form');
  form.className = 'work-package-edit-form';
  form.dataset.workPackageId = item.id;
  form.dataset.lockVersion = item.lock_version;
  addWorkPackageTextField(form, 'Subject', 'subject', item.subject);
  addWorkPackageTextField(form, 'Description', 'description', item.description, true);

  const fields = document.createElement('div');
  fields.className = 'work-package-fields';
  addWorkPackageSelect(fields, 'Status', 'status_id', options.statuses, item.status_id);
  addWorkPackageSelect(fields, 'Priority', 'priority_id', options.priorities, item.priority_id);
  addWorkPackageSelect(fields, 'Assignee', 'assignee_id', options.assignees, item.assignee_id, true);
  form.append(fields);

  const actions = document.createElement('div');
  actions.className = 'work-package-actions';
  const saveButton = document.createElement('button');
  saveButton.type = 'submit';
  saveButton.textContent = 'Save changes';
  actions.append(saveButton);
  form.append(actions);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    saveButton.disabled = true;
    workPackageStatus.textContent = `Saving work item #${item.id}...`;
    const values = new FormData(form);
    const payload = {
      lock_version: Number(form.dataset.lockVersion),
      subject: values.get('subject').trim(),
      description: values.get('description'),
      status_id: Number(values.get('status_id')),
      priority_id: Number(values.get('priority_id')),
      assignee_id: values.get('assignee_id') ? Number(values.get('assignee_id')) : null,
    };

    try {
      const response = await fetch(`/api/admin/work-packages/${item.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.detail || `Save failed (${response.status})`);
      }
      await loadOpenWorkPackages(`Work item #${item.id} saved.`);
    } catch (error) {
      workPackageStatus.textContent = `Could not save work item #${item.id}: ${error.message}`;
      saveButton.disabled = false;
    }
  });

  article.append(heading, form);
  return article;
}

async function loadOpenWorkPackages(successMessage = '') {
  if (!workPackageList || !workPackageStatus) return;
  workPackageStatus.textContent = successMessage || 'Loading open work items...';
  workPackageList.replaceChildren();

  try {
    const response = await fetch('/api/admin/work-packages');
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.detail || `Request failed (${response.status})`);
    }
    const data = await response.json();
    if (!Array.isArray(data.items)) {
      throw new Error('The work-item response was not a list.');
    }
    if (!data.items.length) {
      workPackageStatus.textContent = successMessage || 'No open work items.';
      return;
    }

    const fragment = document.createDocumentFragment();
    for (const item of data.items) {
      fragment.append(renderWorkPackage(item, data));
    }
    workPackageList.append(fragment);
    workPackageStatus.textContent = successMessage || `${data.items.length} open work item(s).`;
  } catch (error) {
    workPackageStatus.textContent = `Could not load open work items: ${error.message}`;
  }
}

async function loadCurrentUser() {
  if (signedOut) signedOut.hidden = true;
  if (signedIn) signedIn.hidden = true;
  if (requestForm) requestForm.hidden = true;
  if (adminPanel) adminPanel.hidden = true;

  try {
    const response = await fetch('/api/me');

    if (response.status === 401) {
      if (signedOut) signedOut.hidden = false;
      if (adminAccessStatus) {
        adminAccessStatus.textContent = 'Sign in with an administrator account to access this page.';
      }
      return;
    }

    if (!response.ok) {
      throw new Error(`Account request failed (${response.status})`);
    }

    const user = await response.json();

    if (accountName) accountName.textContent = user.name || 'User';
    if (accountEmail) accountEmail.textContent = user.email || '';

    if (signedIn) signedIn.hidden = false;
    if (requestForm) requestForm.hidden = false;

    if (user.role === 'admin') {
      if (adminLink) adminLink.hidden = false;
      if (openProjectLink) openProjectLink.hidden = false;
      if (adminPage && adminPanel) {
        if (adminAccessStatus) adminAccessStatus.hidden = true;
        adminPanel.hidden = false;
        await Promise.all([loadAdminUsers(), loadOpenWorkPackages()]);
      }
    } else if (adminAccessStatus) {
      adminAccessStatus.textContent = 'You do not have permission to access administration.';
    }
  } catch (error) {
    console.error('Could not check sign-in status:', error);
    if (adminAccessStatus) {
      adminAccessStatus.textContent = 'Could not verify administrator access. Please reload the page.';
    }
  }
}

async function initializePage() {
  await mountSharedComponents();

  requestForm = document.querySelector('#request-form');
  formStatus = document.querySelector('#form-status');
  signedOut = document.querySelector('#signed-out');
  signedIn = document.querySelector('#signed-in');
  accountName = document.querySelector('#account-name');
  accountEmail = document.querySelector('#account-email');
  signOutButton = document.querySelector('#sign-out-button');
  adminLink = document.querySelector('#admin-link');
  openProjectLink = document.querySelector('#openproject-link');
  adminPage = document.querySelector('#admin-page');
  adminAccessStatus = document.querySelector('#admin-access-status');
  adminPanel = document.querySelector('#admin-panel');
  adminStatus = document.querySelector('#admin-status');
  adminUsers = document.querySelector('#admin-users');
  workPackageList = document.querySelector('#work-package-list');
  workPackageStatus = document.querySelector('#work-package-status');
  refreshWorkPackagesButton = document.querySelector('#refresh-work-packages');

  signOutButton?.addEventListener('click', async () => {
    signOutButton.disabled = true;

    try {
      const response = await fetch('/auth/logout', { method: 'POST' });
      if (!response.ok) throw new Error(`Sign-out failed (${response.status})`);
      window.location.reload();
    } catch (error) {
      console.error('Sign-out failed:', error);
      signOutButton.disabled = false;
    }
  });

  requestForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submitButton = requestForm.querySelector('[type="submit"]');
    submitButton.disabled = true;
    formStatus.replaceChildren();
    formStatus.dataset.state = 'pending';
    formStatus.textContent = 'Submitting your request...';
    const values = new FormData(requestForm);
    const payload = Object.fromEntries(values.entries());

    try {
      const response = await fetch('/api/requests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 401) {
          throw new Error('Please sign in with your CSES affiliate Google account before submitting.');
        }
        throw new Error(result.detail || `Submission failed (${response.status}). Please try again.`);
      }
      if (!result.id) {
        throw new Error('The server did not confirm that your request was created. Please try again.');
      }

      formStatus.replaceChildren(document.createTextNode(`Your request #${result.id} was submitted successfully.`));
      if (result.url) {
        const link = document.createElement('a');
        link.href = result.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = ' View request';
        formStatus.append(link);
      }
      formStatus.dataset.state = 'success';
      requestForm.reset();
    } catch (error) {
      formStatus.dataset.state = 'error';
      formStatus.textContent = `Could not submit request: ${error.message}`;
    } finally {
      submitButton.disabled = false;
    }
  });

  refreshWorkPackagesButton?.addEventListener('click', () => loadOpenWorkPackages());

  if (signedOut && signedIn) {
    loadCurrentUser();
  }
}

initializePage();
