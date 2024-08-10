
$(document).ready(function() {
    // Disable browser validation
    (function () {
        'use strict'
        // Fetch all the forms we want to apply custom Bootstrap validation styles to
        var forms = document.querySelectorAll('.needs-validation')
        // Loop over them and prevent submission
        Array.prototype.slice.call(forms)
            .forEach(function (form) {
                form.addEventListener('submit', function (event) {
                if (!form.checkValidity()) {
                    event.preventDefault()
                    event.stopPropagation()
                }    
                form.classList.add('was-validated')
            }, false)
        })
    })()

    $('form').submit(function(event) {
        event.preventDefault();

        const formArray = $(this).serializeArray();
        const formData = {};
        $.each(formArray, function(index, field){
            if (field.value !== "") {
                if (field.name.includes("regex")) {
                    formData[field.name] = true;
                } else {
                    formData[field.name] = field.value;
                }
            }
        })
        console.log(formData);

        $.ajax({
            url: '/results',
            type: 'GET',
            data: JSON.stringify(formData),
            dataType: "json",
            headers: {'Content-Type': 'application/json'},
            success: function(data) {
                console.log('Success:', data);
                $('html').html(response);
            },
            error: function(xhr, status, error) {
                console.error('Error:', error);
            }
        });
    });
});