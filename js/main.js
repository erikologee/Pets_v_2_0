/*
Template Name: PetZ
Author: Ingrid Kuhn
Author URI: themeforest/user/ingridk
Version: 1.1
*/

 "use strict";
$(document).ready(function() {

	//Scrolling feature 

    $('.page-scroll a').on('click', function(event) {
        var $anchor = $(this);
        $('html, body').stop().animate({
            scrollTop: $($anchor.attr('href')).offset().top
        }, 2500, 'easeInOutExpo');
        event.preventDefault();
    });
			
	// get current URL path and assign 'active' class

	 $(function($) {
	  let url = window.location.href;
	  $('nav ul li a').each(function() {
		if (this.href === url) {
			$(this).addClass('active');
		  $(this).parents('li').find('a.nav-link').addClass('active');
		}
	  });
	});
		
		

    //	Back Top Link

    var offset = 200;
    var duration = 1500;
    $(window).scroll(function() {
        if ($(this).scrollTop() > offset) {
            $('.back-to-top').fadeIn(400);
        } else {
            $('.back-to-top').fadeOut(400);
        }
    });

	//Dropdown on hover
	
	if ($(window).width() > 1200) {				
	$(".navbar .dropdown").on({
		mouseenter: function () {
		$(this).find('.dropdown-menu').first().stop(true, true).delay(50).slideDown();

		},  
		mouseleave: function () {
		$(this).find('.dropdown-menu').first().stop(true, true).delay(100).slideUp();
		}
	});
	}
	
	
    //Slick Slider
	
	$('.slider-center').slick({
		dots: true,
		centerMode: true,
		autoplaySpeed: 2000,
		slidesToShow: 4,
		responsive: [{
				breakpoint: 991,
				settings: {
					slidesToShow: 2,
					slidesToScroll: 1
				}
			},
			{
				breakpoint: 767,
				settings: {
					slidesToShow: 1,
					slidesToScroll: 1
				}
			}
		]
		

	});
	$('.slider-2').slick({
		dots: true,
		autoplaySpeed: 2000,
		slidesToShow: 2,
		responsive: [{
				breakpoint: 600,
				settings: {
					slidesToShow: 1,
					slidesToScroll: 1
				}
			}
		]
	});
	$('.slider-3').slick({
		dots: true,
		autoplaySpeed: 2000,
		slidesToShow: 3,
		responsive: [{
				breakpoint: 1200,
				settings: {
					slidesToShow: 2,
					slidesToScroll: 2
				}
			},
			{
				breakpoint: 600,
				settings: {
					slidesToShow: 1,
					slidesToScroll: 1
				}
			}
		]

	});
	$('.slider-4').slick({
		dots: true,
		autoplaySpeed: 2000,
		slidesToShow: 4,
		responsive: [{
				breakpoint: 1200,
				settings: {
					slidesToShow: 2,
					slidesToScroll: 2
				}
			},
			{
				breakpoint: 600,
				settings: {
					slidesToShow: 1,
					slidesToScroll: 1
				}
			}
		]

	});
	 
		
  
}); // end document ready


// Window scroll function

$(window).on("scroll", function() {
	
	   // Shrink Navbar on Scroll 	

	  if ($(document).scrollTop() > 50) {
		$('nav').addClass('shrink');
	  } else {
		$('nav').removeClass('shrink');
	  }
});

// Window load function

$(window).on("load", function() {

    // Page Preloader 	

    $("#preloader").fadeOut("slow");

    // Magnific Popup
				 
	$('.gallery-thumb,.image-lightbox').magnificPopup({
		delegate: 'a', // child items selector, by clicking on it popup will open
		type: 'image',
		fixedContentPos: false,
		overflowY:'scroll',
		gallery: {
		enabled: true
		}
	});	

    //Isotope 

    var $container = $('#lightbox');
    $container.isotope({
        filter: '*',
        animationOptions: {
            duration: 750,
            easing: 'linear',
            queue: false,
            layoutMode: 'masonry'
        }

    });
    

	//initialize skrollr
	
    skrollr.init({
        smoothScrolling: true,
		forceHeight: false			
    });

    // disable skrollr if using handheld device
	
    if( /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ) {
        skrollr.init().destroy();
    }
	
  	
    //Isotope Nav Filter

    $('.category-isotope a').on('click', function() {
        $('.category-isotope .active').removeClass('active');
        $(this).addClass('active');

        var selector = $(this).attr('data-filter');
        $container.isotope({
            filter: selector,
            animationOptions: {
                duration: 750,
                easing: 'linear',
                queue: false
            }
        });
        return false;
    });
	

}); // end window load
