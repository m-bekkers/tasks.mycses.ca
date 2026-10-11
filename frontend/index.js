const requestForm = document.querySelector('#request-form');
const formStatus = document.querySelector('#form-status');

const authStatus = document.querySelector('#auth-status');
const signedOut = document.querySelector('#signed-out');
const signedIn = document.querySelector('#signed-in');
const accountName = document.querySelector('#account-name');
const accountEmail = document.querySelector('#account-email');
const accountRole = document.querySelector('#account-role');
const signOutButton = document.querySelector('#sign-out-button');

const adminPanel = document.querySelector('#admin-panel');
const adminStatus = document.querySelector('#admin-status');
const adminUsers = document.querySelector('#admin-users');

async function loadAdminUsers() {
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

async function loadCurrentUser() {
  authStatus.textContent = 'Checking sign-in status...';
  signedOut.hidden = true;
  signedIn.hidden = true;
  adminPanel.hidden = true;
  requestForm.hidden = true;

  try {
    const response = await fetch('/api/me');

    if (response.status === 401) {
      authStatus.textContent = 'You are not currently signed in.';
      signedOut.hidden = false;
      return;
    }

    if (!response.ok) {
      throw new Error(`Account request failed (${response.status})`);
    }

    const user = await response.json();

    accountName.textContent = user.name || 'User';
    accountEmail.textContent = user.email || '';
    accountRole.textContent = user.role || 'unknown';

    authStatus.textContent = '';
    signedIn.hidden = false;
    requestForm.hidden = false;

    if (user.role === 'admin') {
      adminPanel.hidden = false;
      await loadAdminUsers();
    }
  } catch (error) {
    authStatus.textContent = `Could not check sign-in status: ${error.message}`;
  }
}

signOutButton.addEventListener('click', async () => {
  signOutButton.disabled = true;

  try {
    const response = await fetch('/auth/logout', { method: 'POST' });

    if (!response.ok) {
      throw new Error(`Sign-out failed (${response.status})`);
    }

    window.location.reload();
  } catch (error) {
    authStatus.textContent = error.message;
    signOutButton.disabled = false;
  }
});

requestForm.addEventListener('submit', (event) => {
  event.preventDefault();
  formStatus.textContent =
    'The form is valid, but no submission service is connected yet.';
});

loadCurrentUser();
