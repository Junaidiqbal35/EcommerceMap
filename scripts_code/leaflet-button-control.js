L.Control.Button = L.Control.extend({
  options: {
    position: 'bottomleft'
  },
  initialize: function (options) {
    this._button = {};
    this.setButton(options);
	if (typeof options.position != 'undefined') this.options.position = options.position;
  },

  onAdd: function (map) {
    this._map = map;
    var container = L.DomUtil.create('div', 'leaflet-control-button');
	
    this._container = container;
    
    this._update();
    return this._container;
  },

  onRemove: function (map) {
  },

  setButton: function (options) {	
	var button = Object.assign({},options);

    this._button = button;
    this._update();
  },
  
  getText: function () {
  	return this._button.text;
  },
  
  getIconUrl: function () {
  	return this._button.iconUrl;
  },
  
  destroy: function () {
  	this._button = {};
  	this._update();
  },
  
  toggle: function (e) {
  	if(typeof e === 'boolean'){
  		this._button.toggleStatus = e;
  	}
  	else{
  		this._button.toggleStatus = !this._button.toggleStatus;
  	}
  	this._update();
  },
  
  _update: function () {
    if (!this._map) {
      return;
    }

    this._container.innerHTML = '';
    this._makeButton(this._button);
 
  },

  _makeButton: function (button) {
    var newButton = L.DomUtil.create('button', 'leaflet-buttons-control-button', this._container);
    if(button.toggleStatus) L.DomUtil.addClass(newButton,'leaflet-buttons-control-toggleon');
    
	if(button.iconUrl) {
		var image = L.DomUtil.create('img', 'leaflet-buttons-control-img', newButton);
		image.setAttribute('src',button.iconUrl);
    }
	
	if(button.classname) L.DomUtil.addClass(newButton, button.classname);
	
    if(button.text !== ''){

      if(button.iconUrl) L.DomUtil.create('br','',newButton);  //there must be a better way

	  newButton.type = 'button';
      newButton.innerHTML = button.text;
      
      if(button.hideText)
        L.DomUtil.addClass(newButton,'leaflet-buttons-control-text-hide');
    }
	
	if(button.title !== ''){
		newButton.setAttribute('title',button.title);
	}

    L.DomEvent
      .addListener(newButton, 'click', L.DomEvent.stop)
      .addListener(newButton, 'click', button.onClick,this)
      .addListener(newButton, 'click', this._clicked,this);
    L.DomEvent.disableClickPropagation(newButton);
    return newButton;

  },
  
  _clicked: function () {  //'this' refers to button
  	if(this._button.doToggle){
  		if(this._button.toggleStatus) {	//currently true, remove class
  			L.DomUtil.removeClass(this._container.childNodes[0],'leaflet-buttons-control-toggleon');
  		}
  		else{
  			L.DomUtil.addClass(this._container.childNodes[0],'leaflet-buttons-control-toggleon');
  		}
  		this.toggle();
  	}
  	return;
  }

});