const requestForm = document.querySelector('#request-form');
const formStatus = document.querySelector('#form-status');

requestForm.addEventListener('submit', (event) => {
  event.preventDefault();
  formStatus.textContent = 'The form is valid, but no submission service is connected yet.';
});
